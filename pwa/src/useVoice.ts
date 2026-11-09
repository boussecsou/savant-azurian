import { useCallback, useEffect, useRef, useState } from "react";
import { getSpeechToken, type SpeechToken } from "./api";
import type { Trace } from "./chat";
import { NARRATION_GAP_MS, NarrationQueue, spokenGreeting, type ToolMoment } from "./narration";
import { micLevelFrom } from "./orb/orbMath";
import { ANSWER_WAIT_MS, LISTEN_IDLE_MS, playbackDeadlineMs, SPEECH_END_SILENCE_MS, speakableText, speechSsml, typedInVoice, VoiceError, voiceFor, wordEnd, type VoiceErrorKind, type VoiceLanguage, type VoiceState } from "./voice";

type Sdk = typeof import("microsoft-cognitiveservices-speech-sdk");

export interface Heard {
  text: string;
  language?: string;
  /** Time the recognizer took to settle on the final text after the last partial one. */
  sttMs?: number;
  /** Typed in the composer while voice mode was on, not spoken. */
  typed?: boolean;
}

/** What the answer being read has reached, for the caption. */
export interface Spoken {
  text: string;
  /** Characters of `text` already said. */
  offset: number;
}

export interface VoiceOptions {
  /** Language the recognizer listens for, and the voice that answers. */
  language: VoiceLanguage;
  /** Read answers (and tool announcements) aloud. Off: the answer stays in the thread. */
  speakAloud: boolean;
  /** A whole turn is over: how long each part took, as measured here. */
  onTurn?: (trace: Trace) => void;
  /** A failure that does not stop voice mode (the answer could not be read aloud). */
  onSoftError?: (kind: VoiceErrorKind) => void;
}

const MUTED = Symbol("muted");
// The recognizer stopped because the owner typed a message: the loop takes it instead.
const TYPED = Symbol("typed");
const IDLE_LEVEL = 0.12;

/**
 * Voice loop: listen (Azure Speech STT) → send the final transcript like a typed message → read the
 * answer aloud (Azure Speech TTS) → listen again, until the owner taps the orb. The SDK is loaded on
 * first use only, and the browser talks to Azure Speech directly with a token from the BFF.
 * While the agent works, `announce(tool, moment)` reads a short fixed phrase when a tool starts
 * ("Je cherche ça sur le web.") and when its result comes back ("Voilà, je regarde les résultats.").
 * The microphone level and spectrum go to refs (never state) so the orb can read them every frame.
 */
export function useVoice(onUtterance: (text: string, heard: Heard) => Promise<string | null>, options: VoiceOptions) {
  const [state, setStateValue] = useState<VoiceState>("off");
  // The current state, readable from callbacks (announcements only play while thinking).
  const phase = useRef<VoiceState>("off");
  const setState = useCallback((next: VoiceState) => {
    phase.current = next;
    setStateValue(next);
  }, []);
  const [partial, setPartial] = useState("");
  const [heard, setHeard] = useState<Heard | null>(null);
  const [spoken, setSpoken] = useState<Spoken | null>(null);
  // The last fixed phrase queued for a tool in this turn ("Je cherche ça sur le web."), shown under the orb while thinking.
  const [announced, setAnnounced] = useState<string | null>(null);
  const [muted, setMutedState] = useState(false);
  const mutedRef = useRef(false);
  const unmuteWaiters = useRef<(() => void)[]>([]);
  const narration = useRef({ queue: new NarrationQueue(undefined), language: undefined as string | undefined, lastAt: 0,
                              running: null as Promise<void> | null });
  // Index of the last acknowledgment said, so the next one differs.
  const lastAck = useRef<number | undefined>(undefined);
  const [error, setError] = useState<VoiceErrorKind | null>(null);
  const active = useRef(false);
  // Which start() is alive. Stopping bumps it, so a loop that was still waiting (a greeting being
  // prepared, a recognizer being created) dies instead of waking up beside a newer loop.
  const run = useRef(0);
  const sdkRef = useRef<Sdk | null>(null);
  const tokenRef = useRef<(SpeechToken & { until: number }) | null>(null);
  const stopCurrent = useRef<(() => void) | null>(null);
  const stopListening = useRef<(() => void) | null>(null);
  // A message typed while voice mode is on, waiting for the loop; and how to hand the recognizer over to it.
  const typed = useRef<string | null>(null);
  const yieldToTyped = useRef<(() => void) | null>(null);
  // The greeting, spoken while the recognizer already listens: it must not stop the recognizer.
  const stopAlongside = useRef<(() => void) | null>(null);
  const utter = useRef(onUtterance);
  utter.current = onUtterance;
  const settings = useRef(options);
  settings.current = options;

  // Microphone level and spectrum for the orb.
  const micLevel = useRef(IDLE_LEVEL);
  const spectrum = useRef<Uint8Array | null>(null);
  const meter = useRef<{ stream: MediaStream; context: AudioContext; frame: number } | null>(null);

  const stopMeter = useCallback(() => {
    const current = meter.current;
    meter.current = null;
    micLevel.current = IDLE_LEVEL;
    spectrum.current = null;
    if (!current) return;
    cancelAnimationFrame(current.frame);
    current.stream.getTracks().forEach((track) => track.stop());
    void current.context.close().catch(() => undefined);
  }, []);

  const startMeter = useCallback(
    (stream: MediaStream) => {
      stopMeter();
      try {
        const context = new AudioContext();
        const analyser = context.createAnalyser();
        analyser.fftSize = 128;
        context.createMediaStreamSource(stream).connect(analyser);
        const bytes = new Uint8Array(analyser.frequencyBinCount);
        const entry = { stream, context, frame: 0 };
        const tick = () => {
          entry.frame = requestAnimationFrame(tick);
          if (phase.current !== "listening" || mutedRef.current) {
            micLevel.current = 0.04;
            spectrum.current = null;
            return;
          }
          analyser.getByteFrequencyData(bytes);
          micLevel.current = micLevelFrom(bytes);
          spectrum.current = bytes;
        };
        entry.frame = requestAnimationFrame(tick);
        meter.current = entry;
      } catch {
        // A second capture can be refused (some phones): the orb then moves on a gentle default.
        stream.getTracks().forEach((track) => track.stop());
      }
    },
    [stopMeter],
  );

  const speechConfig = useCallback(async () => {
    const sdk = (sdkRef.current ??= await import("microsoft-cognitiveservices-speech-sdk"));
    let token = tokenRef.current;
    if (!token || Date.now() > token.until) {
      try {
        const fresh = await getSpeechToken();
        token = tokenRef.current = { ...fresh, until: Date.now() + Math.max(30, fresh.expiresIn - 60) * 1000 };
      } catch {
        throw new VoiceError("token");
      }
    }
    return { sdk, config: sdk.SpeechConfig.fromAuthorizationToken(token.token, token.region) };
  }, []);

  // Load the SDK and fetch a token ahead of the first tap, so listening starts at once.
  const prepare = useCallback(async () => {
    try {
      await speechConfig();
    } catch {
      // Reported on the real start, not on a background preparation.
    }
  }, [speechConfig]);

  const waitUnmuted = useCallback(
    () =>
      new Promise<void>((resolve) => {
        if (!mutedRef.current) resolve();
        else unmuteWaiters.current.push(resolve);
      }),
    [],
  );

  const releaseMuteWaiters = useCallback(() => {
    const waiters = unmuteWaiters.current;
    unmuteWaiters.current = [];
    waiters.forEach((resolve) => resolve());
  }, []);

  const setMuted = useCallback(
    (value: boolean) => {
      mutedRef.current = value;
      setMutedState(value);
      if (value) stopListening.current?.();
      else releaseMuteWaiters();
    },
    [releaseMuteWaiters],
  );

  /**
   * One utterance with live captions: continuous recognition shows partial text as it comes and
   * stops at the first final result. "Listening" is shown only once the microphone stream has
   * really started, so nothing said before is lost. Muting ends the attempt without counting it as silence.
   * `greet`, when given, is spoken the moment listening starts; what the recognizer hears while it
   * plays is ignored (it is Savant's own voice), and the silence timer only starts once it is over.
   */
  const listenOnce = useCallback(async (greet?: () => Promise<void>): Promise<Heard | null | typeof MUTED | typeof TYPED> => {
    const turn = run.current;
    const { sdk, config } = await speechConfig();
    if (turn !== run.current) return null;
    const language = settings.current.language;
    config.speechRecognitionLanguage = language;
    config.setProperty(sdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, String(SPEECH_END_SILENCE_MS));
    const recognizer = new sdk.SpeechRecognizer(config, sdk.AudioConfig.fromDefaultMicrophoneInput());
    return new Promise<Heard | null | typeof MUTED | typeof TYPED>((resolve, reject) => {
      let done = false;
      let idle: ReturnType<typeof setTimeout> | undefined;
      let lastPartialAt = 0;
      let greeting = false;
      const armIdle = () => {
        clearTimeout(idle);
        idle = setTimeout(() => finish(null), LISTEN_IDLE_MS);
      };
      const finish = (result: Heard | null | typeof MUTED | typeof TYPED, failure?: VoiceError) => {
        if (done) return;
        done = true;
        clearTimeout(idle);
        setPartial("");
        stopListening.current = null;
        yieldToTyped.current = null;
        stopAlongside.current?.();
        const close = () => recognizer.close();
        recognizer.stopContinuousRecognitionAsync(close, close);
        if (failure) reject(failure);
        else resolve(result);
      };
      stopCurrent.current = () => finish(null);
      stopListening.current = () => finish(MUTED);
      yieldToTyped.current = () => finish(TYPED);
      // Typed while the recognizer was being prepared: hand over at once.
      if (typed.current !== null) return finish(TYPED);
      recognizer.recognizing = (_, event) => {
        if (greeting) return;
        armIdle();
        lastPartialAt = performance.now();
        setPartial(event.result.text);
      };
      recognizer.recognized = (_, event) => {
        if (greeting) return;
        const text = event.result.text?.trim();
        if (event.result.reason === sdk.ResultReason.RecognizedSpeech && text) {
          finish({ text, language, ...(lastPartialAt ? { sttMs: Math.round(performance.now() - lastPartialAt) } : {}) });
        }
      };
      recognizer.canceled = (_, event) => {
        if (event.reason !== sdk.CancellationReason.Error) return finish(null);
        finish(null, new VoiceError(event.errorCode === sdk.CancellationErrorCode.AuthenticationFailure ? "token" : "stt"));
      };
      recognizer.startContinuousRecognitionAsync(
        () => {
          if (done) return;
          setState("listening");
          if (!greet) return armIdle();
          greeting = true;
          // A courtesy: if it cannot be read, listening goes on anyway.
          greet()
            .catch(() => undefined)
            .finally(() => {
              greeting = false;
              if (!done) armIdle();
            });
        },
        () => finish(null, new VoiceError("stt")),
      );
    });
  }, [speechConfig, setState]);

  /** Read a text aloud. Resolves with the time synthesis took. `follow` reports the words as they are said. */
  const say = useCallback(
    async (text: string, language?: string, follow = false, alongside = false): Promise<number | undefined> => {
      if (!text) return undefined;
      const turn = run.current;
      const { sdk, config } = await speechConfig();
      // Voice mode was stopped (or restarted) while this was being prepared: say nothing.
      if (turn !== run.current) return undefined;
      // One voice at a time: whatever is still being spoken stops first. Not when speaking while the
      // recognizer listens (the greeting): the current slot then holds that recognizer.
      if (!alongside) {
        try {
          stopCurrent.current?.();
        } catch {
          // Already closed: nothing left to stop.
        }
      }
      config.speechSynthesisVoiceName = voiceFor(language);
      const player = new sdk.SpeakerAudioDestination();
      const synthesizer = new sdk.SpeechSynthesizer(config, sdk.AudioConfig.fromSpeakerOutput(player));
      if (follow) {
        setSpoken({ text, offset: 0 });
        let reached = 0;
        synthesizer.wordBoundary = (_, event) => {
          reached = wordEnd(text, reached, event);
          setSpoken({ text, offset: reached });
        };
      }
      const started = performance.now();
      let synthesisMs: number | undefined;
      let ours: (() => void) | null = null;
      let deadline: ReturnType<typeof setTimeout> | undefined;
      try {
        await new Promise<void>((resolve, reject) => {
          ours = () => {
            player.pause();
            synthesizer.close();
            resolve();
          };
          if (alongside) stopAlongside.current = ours;
          else stopCurrent.current = ours;
          player.onAudioEnd = () => resolve();
          synthesizer.speakSsmlAsync(
            speechSsml(text, language),
            (result) => {
              synthesisMs = Math.round(performance.now() - started);
              synthesizer.close();
              if (result.reason !== sdk.ResultReason.SynthesizingAudioCompleted) return reject(new VoiceError("tts"));
              // onAudioEnd does not always come: end at the audio's real length anyway (see voice.ts).
              deadline = setTimeout(resolve, playbackDeadlineMs(result.audioDuration));
            },
            () => {
              synthesizer.close();
              reject(new VoiceError("tts"));
            },
          );
        });
      } finally {
        clearTimeout(deadline);
        if (follow) setSpoken(null);
        if (ours && stopCurrent.current === ours) stopCurrent.current = null;
        if (ours && stopAlongside.current === ours) stopAlongside.current = null;
      }
      return synthesisMs;
    },
    [speechConfig],
  );

  const speak = useCallback(
    (markdown: string, language?: string) => say(speakableText(markdown), language, true),
    [say],
  );

  // Announcements play one at a time, at most one every NARRATION_GAP_MS, and only while thinking.
  const drainNarration = useCallback(async () => {
    const current = narration.current;
    const playing = () => active.current && phase.current === "thinking";
    while (playing()) {
      const wait = NARRATION_GAP_MS - (Date.now() - current.lastAt);
      if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
      const phrase = playing() ? current.queue.take() : null;
      if (!phrase) break;
      try {
        await say(phrase, current.language);
      } catch {
        // An announcement is a courtesy: its failure never breaks the turn.
      }
      current.lastAt = Date.now();
    }
  }, [say]);

  const announce = useCallback(
    (tool: string | undefined, moment: ToolMoment) => {
      const current = narration.current;
      if (!active.current || phase.current !== "thinking" || !settings.current.speakAloud) return;
      setAnnounced(current.queue.offer(tool, moment));
      current.running ??= drainNarration().finally(() => {
        current.running = null;
      });
    },
    [drainNarration],
  );

  const fail = useCallback((kind: VoiceErrorKind) => {
    active.current = false;
    stopMeter();
    releaseMuteWaiters();
    setError(kind);
    setState("error");
  }, [setState, stopMeter, releaseMuteWaiters]);

  const start = useCallback(async () => {
    if (active.current) return;
    active.current = true;
    const mine = ++run.current;
    const alive = () => active.current && run.current === mine;
    setError(null);
    setHeard(null);
    mutedRef.current = false;
    setMutedState(false);
    setState("starting");
    try {
      // Ask for the microphone up front so a refusal is reported as such, not as a recognition failure.
      // The stream stays open for the orb's level meter and closes when voice mode ends.
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      startMeter(stream);
    } catch {
      if (alive()) fail("microphone");
      return;
    }
    if (!alive()) return;
    let silent = 0;
    try {
      // A fixed greeting, so the owner hears Savant is there before saying anything. It is spoken
      // once the microphone really listens (state "listening"), never before: the owner answers
      // it at once, and nothing of the first words is lost. Tapping the orb stops it like any speech.
      let greet: (() => Promise<void>) | undefined = settings.current.speakAloud
        ? async () => {
            await say(spokenGreeting(settings.current.language), settings.current.language, false, true);
          }
        : undefined;
      while (alive()) {
        let result: Heard | null | typeof MUTED | typeof TYPED;
        const written = typed.current;
        if (written !== null) {
          // A message typed in the composer: same turn as a spoken one, answered aloud.
          typed.current = null;
          greet = undefined;
          result = { text: written, language: settings.current.language, typed: true };
        } else {
          if (mutedRef.current) {
            setState("listening");
            await waitUnmuted();
            continue;
          }
          result = await listenOnce(greet);
          greet = undefined;
        }
        if (!alive()) break;
        if (result === TYPED) continue;
        if (result === MUTED) {
          setState("listening");
          await waitUnmuted();
          continue;
        }
        if (!result) {
          // Two silent turns in a row: stop instead of listening forever.
          if (++silent >= 2) break;
          continue;
        }
        silent = 0;
        setHeard(result);
        setAnnounced(null);
        narration.current = { queue: new NarrationQueue(result.language), language: result.language, lastAt: 0, running: null };
        setState("thinking");
        if (settings.current.speakAloud) {
          // At once, without the model: covers the wait while the agent loads its tools. Tool
          // announcements queue behind it and play in order.
          const current = narration.current;
          lastAck.current = current.queue.acknowledge(lastAck.current);
          current.running ??= drainNarration().finally(() => {
            current.running = null;
          });
        }
        const sentAt = performance.now();
        const answer = await utter.current(result.text, result);
        const agentMs = Math.round(performance.now() - sentAt);
        // Let the announcement being spoken finish (a few seconds at most), drop the rest, then read the answer.
        narration.current.queue.clear();
        const announcing = narration.current.running;
        if (announcing) {
          let waited: ReturnType<typeof setTimeout> | undefined;
          const over = await Promise.race([
            announcing.then(() => true),
            new Promise<boolean>((resolve) => {
              waited = setTimeout(() => resolve(false), ANSWER_WAIT_MS);
            }),
          ]);
          clearTimeout(waited);
          // Still "playing" after that: its end was never reported. Cut it and go on.
          if (!over) stopCurrent.current?.();
        }
        if (!alive()) break;
        if (answer === null) {
          fail("agent");
          return;
        }
        let ttsMs: number | undefined;
        if (settings.current.speakAloud) {
          setState("speaking");
          try {
            ttsMs = await speak(answer, result.language);
          } catch (caught) {
            // Not fatal: the answer is in the thread and the conversation goes on.
            if (!(caught instanceof VoiceError) || caught.kind !== "tts") throw caught;
            settings.current.onSoftError?.("tts");
          }
        }
        settings.current.onTurn?.({ ...(result.sttMs !== undefined ? { stt: result.sttMs } : {}), agent: agentMs, ...(ttsMs !== undefined ? { tts: ttsMs } : {}) });
      }
    } catch (caught) {
      if (alive()) fail(caught instanceof VoiceError ? caught.kind : "stt");
      return;
    }
    // A newer start() owns the state now: this loop only ends quietly.
    if (run.current !== mine) return;
    active.current = false;
    stopMeter();
    setState("off");
  }, [drainNarration, fail, listenOnce, say, setState, speak, startMeter, stopMeter, waitUnmuted]);

  /**
   * A message typed while voice mode is on. Returns false when the loop cannot take it (voice off,
   * or a turn already running): the caller then handles it as an ordinary text message, or waits.
   */
  const submit = useCallback(
    (text: string): boolean => {
      const value = text.trim();
      if (!value || !active.current || typedInVoice(phase.current) !== "join") return false;
      typed.current = value;
      // Wherever the loop waits, wake it: listening, muted, or reading an answer aloud.
      yieldToTyped.current?.();
      if (phase.current === "speaking") stopCurrent.current?.();
      releaseMuteWaiters();
      return true;
    },
    [releaseMuteWaiters],
  );

  const stop = useCallback(() => {
    active.current = false;
    typed.current = null;
    run.current++;
    stopCurrent.current?.();
    stopCurrent.current = null;
    stopListening.current = null;
    stopAlongside.current?.();
    stopAlongside.current = null;
    narration.current.queue.clear();
    stopMeter();
    mutedRef.current = false;
    setMutedState(false);
    releaseMuteWaiters();
    setPartial("");
    setSpoken(null);
    setAnnounced(null);
    setError(null);
    setState("off");
  }, [setState, stopMeter, releaseMuteWaiters]);

  useEffect(() => () => {
    active.current = false;
    run.current++;
    stopCurrent.current?.();
    stopAlongside.current?.();
    stopMeter();
    releaseMuteWaiters();
  }, [stopMeter, releaseMuteWaiters]);

  return { state, error, start, stop, submit, announce, prepare, partial, heard, spoken, announced, muted, setMuted, micLevel, spectrum };
}
