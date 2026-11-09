import { useEffect, useImperativeHandle, useRef, useState, type FormEvent, type KeyboardEvent, type Ref } from "react";
import { COUNTER_SHOW, COUNTER_WARN, MAX_LENGTH, applySlash, enterAction, matchSlash, slashQuery } from "../composerKeys";
import { ATTACHMENTS_ENABLED } from "../flags";
import { useFilePicker } from "./Documents";
import { applyMarkdownShortcut, type MarkdownShortcut } from "../markdownShortcuts";
import { Icon } from "./Icon";

const SHORTCUTS: Record<string, MarkdownShortcut> = { b: "bold", i: "italic", e: "code" };

export interface ComposerApi {
  /** Insert text at the cursor (an identifier from the tray, for instance). */
  insert: (text: string) => void;
  focus: () => void;
}

interface Props {
  busy: boolean;
  resume: boolean;
  tech: boolean;
  onTech: () => void;
  /** Unsent text of this session, restored when it is opened. */
  draft: string;
  onDraft: (text: string) => void;
  /** Identifiers seen recently in this session, newest first. */
  recentIds: readonly string[];
  apiRef?: Ref<ComposerApi>;
  onSend: (text: string) => void;
  onResume: () => void;
  /** Adds files to the active project's documents (paperclip or drop on the composer). */
  onAttach?: (files: File[]) => void;
  /** Where an added file goes, for the paperclip's label: "Main". */
  attachTo?: string;
  /** Chat-only view: the voice stage is hidden, so the microphone lives here. */
  voice?: { on: boolean; label: string; onToggle: () => void };
}

/** Made for pasting IDs, logs and code. One instance per session (keyed), so each keeps its own draft. */
export function Composer({ busy, resume, tech, onTech, draft, onDraft, recentIds, apiRef, onSend, onResume, onAttach, attachTo, voice }: Props) {
  const files = useFilePicker((picked) => onAttach?.(picked));
  const [text, setText] = useState(draft);
  const [slashIndex, setSlashIndex] = useState(0);
  const [slashClosed, setSlashClosed] = useState(false);
  const field = useRef<HTMLTextAreaElement>(null);
  const pendingSelection = useRef<[number, number] | null>(null);
  const textRef = useRef(text);
  textRef.current = text;
  const draftSink = useRef(onDraft);
  draftSink.current = onDraft;
  const canSend = text.trim().length > 0 && !busy;
  const slash = slashClosed ? [] : matchSlash(text);

  // Keep the draft: shortly after typing, and when this session is left.
  useEffect(() => {
    const timer = window.setTimeout(() => draftSink.current(text), 400);
    return () => window.clearTimeout(timer);
  }, [text]);
  useEffect(() => () => draftSink.current(textRef.current), []);

  const setValue = (value: string, selection?: [number, number]) => {
    if (selection) pendingSelection.current = selection;
    setText(value);
    setSlashClosed(false);
    setSlashIndex(0);
  };

  const insertAtCursor = (value: string) => {
    const element = field.current;
    const start = element?.selectionStart ?? textRef.current.length;
    const end = element?.selectionEnd ?? start;
    const next = textRef.current.slice(0, start) + value + textRef.current.slice(end);
    setValue(next, [start + value.length, start + value.length]);
    element?.focus();
  };

  useImperativeHandle(apiRef, () => ({ insert: insertAtCursor, focus: () => field.current?.focus() }));

  // Grow with the content, up to 190px, then scroll inside the field.
  useEffect(() => {
    const element = field.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 190)}px`;
  }, [text, tech]);

  // A Markdown shortcut or a "/" command rewrites the value: put the caret back where it belongs.
  useEffect(() => {
    const element = field.current;
    const selection = pendingSelection.current;
    if (!element || !selection) return;
    pendingSelection.current = null;
    element.setSelectionRange(selection[0], selection[1]);
  }, [text]);

  // Do not pop the keyboard open on touch devices.
  useEffect(() => {
    if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) field.current?.focus();
  }, []);

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (!canSend) return;
    onSend(text.trim());
    setText("");
    draftSink.current("");
  };

  const pick = (index: number) => {
    const command = slash[index];
    if (!command) return;
    const { value, cursor } = applySlash(command);
    setValue(value, [cursor, cursor]);
    field.current?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    const mod = event.metaKey || event.ctrlKey;
    const composing = event.nativeEvent.isComposing;

    // The "/" menu is driven by the keyboard and does not animate. Ctrl/⌘+Enter still sends.
    if (slash.length > 0 && !composing) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        setSlashIndex((i) => (event.key === "ArrowDown" ? (i + 1) % slash.length : (i - 1 + slash.length) % slash.length));
        return;
      }
      if ((event.key === "Enter" && !mod) || event.key === "Tab") {
        event.preventDefault();
        pick(slashIndex);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        setSlashClosed(true);
        return;
      }
    }

    if (event.key === "Enter") {
      const action = enterAction({ shift: event.shiftKey, mod, composing }, tech);
      if (action === "send") {
        event.preventDefault();
        submit();
      }
      return;
    }

    // Ctrl/Cmd+B, Ctrl/Cmd+I and Ctrl/Cmd+E wrap the selection in Markdown markers.
    const shortcut = mod ? SHORTCUTS[event.key.toLowerCase()] : undefined;
    if (!shortcut || event.altKey || event.shiftKey || composing) return;
    event.preventDefault();
    const element = event.currentTarget;
    const next = applyMarkdownShortcut({ value: element.value, start: element.selectionStart, end: element.selectionEnd }, shortcut);
    setValue(next.value, [next.start, next.end]);
  };

  const length = text.length;
  return (
    <div className="composer-wrap">
      {recentIds.length > 0 && (
        <div className="idtray" aria-label="Recent IDs">
          <span className="label">Recent IDs</span>
          {recentIds.map((id) => (
            <button type="button" key={id} className="idchip" title="Insert into the message" onClick={() => insertAtCursor(id)}>
              {id}
            </button>
          ))}
        </div>
      )}
      {resume && !busy && (
        <button type="button" className="chip resume press" onClick={onResume}>
          Notion is connected — resume my request
        </button>
      )}
      {slash.length > 0 && (
        <div className="slash" role="listbox" aria-label="Commands">
          {slash.map((command, index) => (
            <button type="button" key={command.name} role="option" aria-selected={index === slashIndex} onMouseDown={(event) => event.preventDefault()} onClick={() => pick(index)}>
              <b>{command.name}</b>
              <span>{command.hint}</span>
            </button>
          ))}
        </div>
      )}
      <form className="composer" data-tech={tech ? "on" : "off"} onSubmit={submit} autoComplete="off">
        <textarea
          ref={field}
          value={text}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          maxLength={MAX_LENGTH}
          placeholder="Write to Savant — paste IDs, logs or code"
          aria-label="Message to Savant"
          enterKeyHint={tech ? "enter" : "send"}
          spellCheck={!tech}
          autoCapitalize={tech ? "off" : undefined}
          autoCorrect={tech ? "off" : undefined}
        />
        <div className="composer-bar">
          {ATTACHMENTS_ENABLED && onAttach ? (
            <>
              <button type="button" className="icon-btn sm press" aria-label={`Add a document to ${attachTo ?? "this project"}'s sources`} title={`Add to ${attachTo ?? "this project"}'s sources (PDF, Word, PowerPoint, text, Markdown)`} onClick={files.pick}>
                <Icon name="paperclip" />
              </button>
              {files.input}
            </>
          ) : (
            <button type="button" className="icon-btn sm press" disabled aria-label="Attach a file (not available yet)" title="Attachments are not available yet">
              <Icon name="paperclip" />
            </button>
          )}
          <button type="button" className="icon-btn sm press" aria-pressed={tech} aria-label="Technical mode" title="Technical mode: monospace, Enter adds a line" onClick={onTech}>
            <Icon name="code" />
          </button>
          <button
            type="button"
            className="icon-btn sm press"
            aria-label="Commands"
            title="Commands (/)"
            onClick={() => {
              if (slashQuery(text) === null && text === "") setValue("/");
              field.current?.focus();
            }}
          >
            <Icon name="slash" />
          </button>
          {voice && (
            <button type="button" className="icon-btn sm press mic" aria-pressed={voice.on} aria-label={voice.on ? "Stop voice mode" : "Start voice mode"} title={voice.label} onClick={voice.onToggle}>
              <Icon name="mic" />
            </button>
          )}
          <span className="spacer" />
          {length > COUNTER_SHOW && (
            <span className="counter" data-warn={length > COUNTER_WARN ? "" : undefined} aria-label={`${length} of ${MAX_LENGTH} characters`}>
              {length}/{MAX_LENGTH}
            </span>
          )}
          <button type="submit" className="send press" disabled={!canSend} aria-label="Send">
            <Icon name="send" size="md" />
          </button>
        </div>
      </form>
      <div className="composer-hint">
        <span>
          {tech ? (
            <>
              <kbd>Ctrl</kbd>+<kbd>Enter</kbd> to send · <kbd>Enter</kbd> adds a line
            </>
          ) : (
            <>
              <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> for a new line · <kbd>/</kbd> for commands
            </>
          )}
        </span>
      </div>
    </div>
  );
}
