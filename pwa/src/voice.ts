/**
 * Voice mode, pure part: states, captions, error kinds, voice choice and the text actually read
 * aloud. The browser talks to Azure Speech directly with a short-lived token from the BFF; the
 * agent only ever receives the final transcript, like a typed message.
 */

export type VoiceState = "off" | "starting" | "listening" | "thinking" | "speaking" | "error";

/**
 * What a typed message does while voice mode is on. Chat and voice are two inputs of the same
 * conversation: a typed message joins the voice loop (its answer is read aloud) whenever the loop
 * could take a spoken one, and cuts an answer being read. While a turn is running it waits (the
 * composer is busy); when voice mode is off or broken it is an ordinary text message.
 */
export function typedInVoice(state: VoiceState): "join" | "busy" | "text" {
  if (state === "off" || state === "error") return "text";
  return state === "thinking" ? "busy" : "join";
}

/** Where a voice turn failed, so the owner knows which part to check. */
export type VoiceErrorKind = "microphone" | "token" | "stt" | "agent" | "tts";

// French first: it is the default language of the voice mode.
export const VOICE_LANGUAGES = ["fr-FR", "en-US"] as const;
export type VoiceLanguage = (typeof VOICE_LANGUAGES)[number];

/**
 * The language the recognizer listens for. A fixed language starts faster and recognizes better
 * than detecting French or English at the start of every utterance, so the owner picks it (Settings
 * or the FR/EN button under the orb) instead of the app guessing on every utterance.
 */
export const VOICE_LANGUAGE: VoiceLanguage = "fr-FR";

export const VOICE_LANGUAGE_KEY = "sa2-voice-language";

export function isVoiceLanguage(value: unknown): value is VoiceLanguage {
  return value === "fr-FR" || value === "en-US";
}

export function loadVoiceLanguage(storage?: Pick<Storage, "getItem">): VoiceLanguage {
  try {
    const raw = (storage ?? window.localStorage).getItem(VOICE_LANGUAGE_KEY);
    return isVoiceLanguage(raw) ? raw : VOICE_LANGUAGE;
  } catch {
    return VOICE_LANGUAGE;
  }
}

export function saveVoiceLanguage(language: VoiceLanguage, storage?: Pick<Storage, "setItem">): void {
  try {
    (storage ?? window.localStorage).setItem(VOICE_LANGUAGE_KEY, language);
  } catch {
    // Blocked or full: the choice lasts for this page only.
  }
}

/** "FR" / "EN" for the small language button. */
export function languageLabel(language: string | undefined): string {
  return language?.toLowerCase().startsWith("en") ? "EN" : "FR";
}

/**
 * Silence that ends an utterance: the recognizer waits this long after the last word before it
 * settles on the final text, so a pause to think does not cut the owner off. (Azure Speech accepts
 * 100 to 5000 ms.)
 */
export const SPEECH_END_SILENCE_MS = 2000;

/** Stop listening after this long without any speech (counts as a silent turn). */
export const LISTEN_IDLE_MS = 8000;

export class VoiceError extends Error {
  constructor(public readonly kind: VoiceErrorKind) {
    super(kind);
  }
}

export const VOICE_CAPTIONS: Record<Exclude<VoiceState, "error">, string> = {
  off: "Tap the orb and speak — or type on the right.",
  starting: "Starting voice…",
  listening: "Listening… speak now",
  thinking: "Thinking…",
  speaking: "Speaking… tap the orb to stop",
};

const ERRORS: Record<VoiceErrorKind, string> = {
  microphone: "Microphone unavailable. Allow microphone access for this page, then tap the orb again.",
  token: "Voice is not available: the gateway did not provide a Speech token.",
  stt: "Speech recognition failed. Tap the orb to try again.",
  agent: "The agent did not answer. Tap the orb to try again.",
  tts: "The answer could not be read aloud; it is shown in the thread.",
};

export function voiceErrorMessage(kind: VoiceErrorKind): string {
  return ERRORS[kind];
}

/**
 * A natural neural voice for the language the owner spoke in: French unless it was English. Both
 * are multilingual voices, so an English word inside a French answer is read in English (the
 * service detects the language of the text), and the other way round.
 */
export function voiceFor(language: string | undefined): string {
  return language?.toLowerCase().startsWith("en") ? "en-US-AvaMultilingualNeural" : "fr-FR-VivienneMultilingualNeural";
}

/** A little faster than the default (Azure accepts 0.5 to 2 times). */
export const SPEECH_RATE = "+15%";

/**
 * A phrase is over when the speaker says so (onAudioEnd), but that event sometimes never comes (a short
 * clip, audio suspended by the browser). So a phrase also ends at its real length plus this margin, and
 * the answer never waits longer than ANSWER_WAIT_MS for an announcement still "playing".
 */
export const PLAYBACK_MARGIN_MS = 1200;
export const ANSWER_WAIT_MS = 5000;

/** When to treat a phrase as over, from Azure's audio duration (100-nanosecond ticks). */
export function playbackDeadlineMs(audioDurationTicks: number | undefined): number {
  if (!audioDurationTicks || audioDurationTicks <= 0) return ANSWER_WAIT_MS;
  return Math.round(audioDurationTicks / 10_000) + PLAYBACK_MARGIN_MS;
}

function xmlEscape(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;");
}

/** The text as SSML: the chosen voice, a little faster. The text is escaped, never trusted as markup. */
export function speechSsml(text: string, language: string | undefined, rate: string = SPEECH_RATE): string {
  const locale = language?.toLowerCase().startsWith("en") ? "en-US" : "fr-FR";
  return (
    `<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="${locale}">` +
    `<voice name="${voiceFor(language)}"><prosody rate="${rate}">${xmlEscape(text)}</prosody></voice></speak>`
  );
}

/**
 * Where the voice has reached in `text` after a word-boundary event. The service may report offsets
 * in the SSML it was sent rather than in the plain text, so the offset is used only when it points
 * at that very word; otherwise the word is looked for after the last position reached.
 */
export function wordEnd(text: string, from: number, event: { text: string; textOffset: number; wordLength: number }): number {
  const end = event.textOffset + event.wordLength;
  if (text.slice(event.textOffset, end) === event.text) return end;
  const found = event.text ? text.indexOf(event.text, from) : -1;
  return found >= 0 ? found + event.text.length : from;
}

export const MAX_SPOKEN_CHARS = 1200;

/** Markdown as it should sound: no markup, no URLs, code and tables left to the screen. */
export function speakableText(markdown: string): string {
  let text = markdown
    .replace(/```[\s\S]*?```/g, " (code shown on screen) ")
    .replace(/^\s*\|.*\|\s*$/gm, "")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s*>\s?/gm, "")
    .replace(/^\s*(?:[-*+]|\d+[.)])\s+/gm, "")
    .replace(/[*_~]+/g, "")
    .replace(/\(\s*\)/g, "")
    .replace(/\s+/g, " ")
    .trim();
  if (text.length > MAX_SPOKEN_CHARS) {
    const cut = text.slice(0, MAX_SPOKEN_CHARS);
    const end = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("? "), cut.lastIndexOf("! "));
    text = (end > 200 ? cut.slice(0, end + 1) : cut) + " The rest is on screen.";
  }
  return text;
}

/** Labels of the status chip above the orb. */
export const STATUS_LABELS = {
  off: "Ready",
  starting: "Starting voice",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
  error: "Voice error",
  muted: "Muted",
} as const;

export interface CaptionWord {
  text: string;
  /** Already said. */
  on: boolean;
}

/**
 * The words of the answer being read, one short stretch at a time: the sentence being said and the
 * next ones (up to `sentences`), with the words already spoken marked. `offset` is how many
 * characters of `text` the voice has reached. The full text stays in the thread.
 */
export function captionWords(text: string, offset: number, sentences = 3): CaptionWord[] {
  const parts: { text: string; start: number }[] = [];
  const pattern = /[^.!?…]+[.!?…]*\s*/g;
  for (const match of text.matchAll(pattern)) {
    if (match[0].trim()) parts.push({ text: match[0], start: match.index ?? 0 });
  }
  if (parts.length === 0) return [];
  let current = 0;
  for (let i = 0; i < parts.length; i++) if (parts[i].start <= offset) current = i;
  const words: CaptionWord[] = [];
  for (const part of parts.slice(current, current + sentences)) {
    let position = part.start;
    for (const word of part.text.split(/(\s+)/)) {
      if (word.trim()) words.push({ text: word, on: position + word.length <= offset });
      position += word.length;
    }
  }
  return words;
}
