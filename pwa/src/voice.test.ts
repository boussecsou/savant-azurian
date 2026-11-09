import { describe, expect, it } from "vitest";
import { ANSWER_WAIT_MS, LISTEN_IDLE_MS, PLAYBACK_MARGIN_MS, playbackDeadlineMs, MAX_SPOKEN_CHARS, SPEECH_END_SILENCE_MS, SPEECH_RATE, VOICE_LANGUAGE_KEY, captionWords, languageLabel, loadVoiceLanguage, saveVoiceLanguage, speakableText, speechSsml, typedInVoice, voiceErrorMessage, voiceFor, wordEnd } from "./voice";

describe("speakableText", () => {
  it("reads prose and drops markup, links and URLs", () => {
    expect(speakableText("## Weather\n**Cloudy**, see [AccuWeather](https://x.example/a) or https://y.example.")).toBe(
      "Weather Cloudy, see AccuWeather or",
    );
  });

  it("leaves code and tables to the screen", () => {
    const text = speakableText("Here:\n```bash\nrm -rf /\n```\n| A | B |\n|---|---|\n| 1 | 2 |\nDone.");
    expect(text).toBe("Here: (code shown on screen) Done.");
  });

  it("reads list items without their markers", () => {
    expect(speakableText("- one\n- two\n1. three")).toBe("one two three");
  });

  it("caps long answers at a sentence boundary", () => {
    const long = "This is a sentence. ".repeat(200);
    const spoken = speakableText(long);
    expect(spoken.length).toBeLessThan(MAX_SPOKEN_CHARS + 40);
    expect(spoken.endsWith("The rest is on screen.")).toBe(true);
  });
});

describe("voice choice and errors", () => {
  it("speaks French by default and English when the owner spoke English", () => {
    expect(voiceFor("fr-FR")).toBe("fr-FR-VivienneMultilingualNeural");
    expect(voiceFor("en-US")).toBe("en-US-AvaMultilingualNeural");
    expect(voiceFor(undefined)).toBe("fr-FR-VivienneMultilingualNeural");
  });

  it("names each failing part", () => {
    expect(voiceErrorMessage("microphone")).toMatch(/Microphone/);
    expect(voiceErrorMessage("stt")).toMatch(/recognition/);
    expect(voiceErrorMessage("agent")).toMatch(/agent/);
    expect(voiceErrorMessage("tts")).toMatch(/read aloud/);
  });
});

describe("voice language", () => {
  it("defaults to French and remembers the owner's choice", () => {
    const data = new Map<string, string>();
    const storage = { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
    expect(loadVoiceLanguage(storage)).toBe("fr-FR");
    saveVoiceLanguage("en-US", storage);
    expect(data.get(VOICE_LANGUAGE_KEY)).toBe("en-US");
    expect(loadVoiceLanguage(storage)).toBe("en-US");
    data.set(VOICE_LANGUAGE_KEY, "de-DE");
    expect(loadVoiceLanguage(storage)).toBe("fr-FR");
    expect(loadVoiceLanguage({ getItem: () => { throw new Error("blocked"); } })).toBe("fr-FR");
  });

  it("labels the language button", () => {
    expect(languageLabel("fr-FR")).toBe("FR");
    expect(languageLabel("en-US")).toBe("EN");
    expect(languageLabel(undefined)).toBe("FR");
  });
});

describe("captionWords", () => {
  const text = "First one. Second sentence here. Third. Fourth is last.";

  it("starts at the sentence being said and shows the next two", () => {
    const words = captionWords(text, 0);
    expect(words.map((w) => w.text).join(" ")).toBe("First one. Second sentence here. Third.");
    expect(words.every((w) => !w.on)).toBe(true);
  });

  it("marks the words already said and moves on with the voice", () => {
    const mid = captionWords(text, "First one. Second".length);
    expect(mid.map((w) => w.text).join(" ")).toBe("Second sentence here. Third. Fourth is last.");
    expect(mid.filter((w) => w.on).map((w) => w.text)).toEqual(["Second"]);
  });

  it("is empty for no text", () => {
    expect(captionWords("", 0)).toEqual([]);
    expect(captionWords("   ", 3)).toEqual([]);
  });
});

describe("end-of-speech silence", () => {
  it("waits about two seconds, within what Azure Speech accepts, and under the idle limit", () => {
    expect(SPEECH_END_SILENCE_MS).toBe(2000);
    expect(SPEECH_END_SILENCE_MS).toBeGreaterThanOrEqual(100);
    expect(SPEECH_END_SILENCE_MS).toBeLessThanOrEqual(5000);
    expect(SPEECH_END_SILENCE_MS).toBeLessThan(LISTEN_IDLE_MS);
  });
});

describe("speechSsml", () => {
  it("wraps the text in the chosen multilingual voice, a little faster", () => {
    const ssml = speechSsml("Bonjour", "fr-FR");
    expect(ssml).toContain('xml:lang="fr-FR"');
    expect(ssml).toContain('<voice name="fr-FR-VivienneMultilingualNeural">');
    expect(ssml).toContain(`<prosody rate="${SPEECH_RATE}">Bonjour</prosody>`);
    expect(speechSsml("Hello", "en-US")).toContain('<voice name="en-US-AvaMultilingualNeural">');
  });

  it("speeds up by a modest amount within what Azure accepts", () => {
    const percent = Number(SPEECH_RATE.replace("%", ""));
    expect(percent).toBeGreaterThan(0);
    expect(percent).toBeLessThanOrEqual(30);
  });

  it("escapes the text, so an answer can never inject markup", () => {
    const ssml = speechSsml('Tom & Jerry <break time="9s"/> "ok"', "fr-FR");
    expect(ssml).toContain("Tom &amp; Jerry &lt;break time=&quot;9s&quot;/&gt; &quot;ok&quot;");
    expect(ssml).not.toContain("<break");
  });
});

describe("wordEnd", () => {
  const text = "Je cherche le meeting de demain.";
  it("uses the reported offset when it points at the word", () => {
    expect(wordEnd(text, 0, { text: "cherche", textOffset: 3, wordLength: 7 })).toBe(10);
  });

  it("looks the word up after the last position when the offset is in the SSML instead", () => {
    expect(wordEnd(text, 10, { text: "meeting", textOffset: 190, wordLength: 7 })).toBe(21);
  });

  it("stays where it was when the word is not found", () => {
    expect(wordEnd(text, 10, { text: "absent", textOffset: 5, wordLength: 6 })).toBe(10);
  });
});

describe("typed messages in voice mode", () => {
  it("join the voice loop, wait during a turn, and stay plain text when voice is off", () => {
    expect(typedInVoice("listening")).toBe("join");
    expect(typedInVoice("speaking")).toBe("join");
    expect(typedInVoice("starting")).toBe("join");
    expect(typedInVoice("thinking")).toBe("busy");
    expect(typedInVoice("off")).toBe("text");
    expect(typedInVoice("error")).toBe("text");
  });
});

describe("never stuck on a phrase whose end is not reported", () => {
  // The speaker's onAudioEnd sometimes never fires (short clip, suspended audio): the turn then hung
  // in "Thinking" with the answer on screen and never read aloud.
  it("ends a phrase from its real audio length, plus a margin", () => {
    // Azure reports audio duration in 100-nanosecond ticks: 2 s = 20 000 000.
    expect(playbackDeadlineMs(20_000_000)).toBe(2000 + PLAYBACK_MARGIN_MS);
  });

  it("falls back to a bounded wait when the length is unknown", () => {
    expect(playbackDeadlineMs(undefined)).toBe(ANSWER_WAIT_MS);
    expect(playbackDeadlineMs(0)).toBe(ANSWER_WAIT_MS);
  });

  it("waits at most a few seconds for an announcement before reading the answer", () => {
    expect(ANSWER_WAIT_MS).toBeGreaterThanOrEqual(3000);
    expect(ANSWER_WAIT_MS).toBeLessThanOrEqual(8000);
  });
});
