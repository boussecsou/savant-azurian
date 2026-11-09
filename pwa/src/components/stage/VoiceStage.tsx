import type { MutableRefObject, ReactNode } from "react";
import type { Heard, Spoken } from "../../useVoice";
import { orbMode } from "../../orb/orbPalette";
import { STATUS_LABELS, VOICE_CAPTIONS, captionWords, languageLabel, voiceErrorMessage, type VoiceErrorKind, type VoiceState } from "../../voice";
import { Icon } from "../Icon";
import { OrbCanvas } from "./OrbCanvas";

interface Props {
  state: VoiceState;
  error: VoiceErrorKind | null;
  muted: boolean;
  /** What the recognizer is hearing right now. */
  partial: string;
  /** The last final utterance. */
  heard: Heard | null;
  /** The answer being read aloud, and how far the voice is. */
  spoken: Spoken | null;
  /** The fixed phrase last read for a tool ("Je cherche ça sur le web."). */
  announced: string | null;
  language: string;
  micLevel: MutableRefObject<number>;
  spectrum: MutableRefObject<Uint8Array | null>;
  isDark: boolean;
  reducedMotion: boolean;
  suggestions: readonly string[];
  onToggle: () => void;
  onMute: () => void;
  onEnd: () => void;
  onLanguage: () => void;
  onSuggest: (text: string) => void;
}

function Glyph({ mode }: { mode: keyof typeof STATUS_LABELS }) {
  if (mode === "starting" || mode === "thinking") return <span className="spinner" aria-hidden="true" />;
  if (mode === "listening" || mode === "speaking") {
    return (
      <span className="eq" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
    );
  }
  return <span className="pip" aria-hidden="true" />;
}

/** The last two words of a partial hypothesis are still "in progress": the recognizer rewrites them. */
function Hypothesis({ text }: { text: string }) {
  const words = text.split(/\s+/).filter(Boolean);
  return (
    <>
      {words.map((word, index) => (
        <span key={index} className={index >= words.length - 2 ? "w live" : "w on"}>
          {word}{" "}
        </span>
      ))}
    </>
  );
}

/** The centre of the screen: status chip, the orb, what is being heard or said, and the voice controls. */
export function VoiceStage(props: Props) {
  const { state, error, muted, partial, heard, spoken, announced, language } = props;
  const active = state !== "off" && state !== "error";
  const mode = orbMode(state, muted);
  const label = STATUS_LABELS[mode];
  const detected = heard?.language ?? language;

  let caption: ReactNode;
  let live: "polite" | "off" = "polite";
  if (state === "error" && error) {
    caption = <span className="err">{voiceErrorMessage(error)}</span>;
  } else if (state === "off") {
    caption = <span className="hint">{VOICE_CAPTIONS.off}</span>;
  } else if (state === "starting") {
    caption = <span className="hint">{VOICE_CAPTIONS.starting}</span>;
  } else if (state === "listening") {
    // Partial words change many times a second: they are not read out by screen readers, the final text is.
    live = "off";
    caption = muted ? (
      <span className="hint">Muted — unmute to speak.</span>
    ) : partial ? (
      <Hypothesis text={partial} />
    ) : (
      <span className="hint">{VOICE_CAPTIONS.listening}</span>
    );
  } else if (state === "thinking") {
    caption = (
      <>
        {heard && <span className="w">{heard.text}</span>}
        <small>{announced ?? VOICE_CAPTIONS.thinking}</small>
      </>
    );
  } else {
    const words = spoken ? captionWords(spoken.text, spoken.offset) : [];
    caption = words.length ? (
      words.map((word, index) => (
        <span key={index} className={word.on ? "w on" : "w"}>
          {word.text}{" "}
        </span>
      ))
    ) : (
      <span className="hint">Speaking…</span>
    );
  }

  return (
    <div className="zone" id="zone">
      <div className="zone-top">
        <div className="status" data-s={mode} role="status">
          <span className="glyph">
            <Glyph mode={mode} />
          </span>
          <span>{label}</span>
          {active && <span className="sub">{languageLabel(detected)}</span>}
        </div>
      </div>
      <div className="orb-wrap">
        <OrbCanvas mode={mode} micLevel={props.micLevel} spectrum={props.spectrum} isDark={props.isDark} reducedMotion={props.reducedMotion} />
        <button
          type="button"
          className="orb"
          aria-pressed={active}
          aria-label={state === "error" ? "Try voice again" : active ? "Stop voice mode" : "Talk to Savant"}
          onClick={props.onToggle}
        />
      </div>
      <div className="zone-bottom">
        <p className="caption" aria-live={live}>
          {caption}
        </p>
        <div className="swap">
          <div className="controls" data-on={active ? "" : undefined} inert={!active}>
            <button type="button" className="btn sm press" aria-label={`Spoken language: ${languageLabel(language)}. Switch`} onClick={props.onLanguage}>
              <Icon name="globe" />
              {languageLabel(language)}
            </button>
            <button type="button" className="btn sm press" aria-pressed={muted} onClick={props.onMute}>
              <Icon name="mic" />
              {muted ? "Unmute" : "Mute"}
            </button>
            <button type="button" className="btn sm press danger" onClick={props.onEnd}>
              <Icon name="stop" />
              End
            </button>
          </div>
          <div className="chips idle-only" inert={active}>
            {props.suggestions.map((text) => (
              <button type="button" key={text} className="chip press" onClick={() => props.onSuggest(text)}>
                {text}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
