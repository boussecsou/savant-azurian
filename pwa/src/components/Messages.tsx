import { useCallback, useEffect, useRef, useState } from "react";
import { formatDuration } from "../activity";
import { errorMessage } from "../api";
import type { ChatMessage } from "../chat";
import { Markdown } from "../markdown";
import { useReveal } from "../useReveal";
import { SourceChips } from "./Documents";
import { Icon } from "./Icon";
import { ToolSteps } from "./ToolSteps";

/** Whole seconds since `active` turned true; 0 while idle. */
function useElapsed(active: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) {
      setSeconds(0);
      return;
    }
    const started = Date.now();
    const timer = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return seconds;
}

/** The agent said it cannot read the workspace: the way forward is the connections in Settings. */
const NEEDS_CONNECTION = new Set(["connect_notion", "oauth_consent_required"]);

function Trace({ message }: { message: ChatMessage }) {
  const trace = message.trace;
  if (!trace) return null;
  const parts: [string, number | undefined][] = [["STT", trace.stt], ["Agent", trace.agent], ["TTS", trace.tts]];
  const shown = parts.filter((part): part is [string, number] => part[1] !== undefined);
  if (shown.length === 0) return null;
  return (
    <div className="trace" aria-label="Voice turn timings">
      {shown.map(([name, ms]) => (
        <span key={name}>
          {name} {formatDuration(ms)}
        </span>
      ))}
    </div>
  );
}

/** The agent's turn: its tool calls, then its words, written out progressively. */
interface SourcesContext {
  /** The project the documents belong to (the session's project). */
  projectId: string;
  /** Ids of the project's documents that exist now: only those open. */
  known: ReadonlySet<string>;
}

function AssistantTurn({ message, onCopy, onOpenSettings, sources }: { message: ChatMessage; onCopy: (text: string) => void; onOpenSettings: () => void; sources?: SourcesContext }) {
  const { shown, catchingUp } = useReveal(message.text, message.live === true);
  const writing = message.streaming === true || catchingUp;
  const needsConnection = !writing && message.tools?.some((tool) => NEEDS_CONNECTION.has(tool.name));
  return (
    <div className="msg assistant">
      {message.tools && message.tools.length > 0 && <ToolSteps tools={message.tools} />}
      {shown && <Markdown text={shown} />}
      {writing && <span className="caret" aria-hidden="true" />}
      {sources && message.sources && message.sources.length > 0 && (
        <SourceChips sources={message.sources} projectId={sources.projectId} known={sources.known} />
      )}
      {!writing && message.text && (
        <div className="msg-acts">
          <button type="button" className="icon-btn sm press" aria-label="Copy answer" title="Copy" onClick={() => onCopy(message.text)}>
            <Icon name="copy" />
          </button>
          {needsConnection && (
            <button type="button" className="text-btn" onClick={onOpenSettings}>
              Open connections
            </button>
          )}
        </div>
      )}
      {!writing && <Trace message={message} />}
    </div>
  );
}

interface Props {
  messages: ChatMessage[];
  busy: boolean;
  onRetry: () => void;
  onCopy: (text: string) => void;
  onOpenSettings: () => void;
  /** Offered after the agent refused to continue an old thread: forgets it and asks again in this session. */
  onStartFresh?: () => void;
  /** Where the sources of answers point; absent when documents are off. */
  sources?: SourcesContext;
}

export function Messages({ messages, busy, onRetry, onCopy, onOpenSettings, onStartFresh, sources }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const thread = useRef<HTMLDivElement>(null);
  const stuckToBottom = useRef(true);
  const last = messages[messages.length - 1];
  // Before the first word or tool call there is nothing to show yet: the dots stand in.
  const waiting = busy && last?.role === "user";
  const hasThread = messages.length > 0 || busy;
  const elapsed = useElapsed(waiting);

  // A new message from the reader scrolls into view smoothly.
  useEffect(() => {
    const element = scroller.current;
    if (!element || last?.role !== "user") return;
    const reduce = document.documentElement.dataset.motion === "reduce";
    stuckToBottom.current = true;
    element.scrollTo({ top: element.scrollHeight, behavior: reduce ? "auto" : "smooth" });
  }, [last?.id, last?.role]);

  // A soft gradient at an edge hints that more text lies beyond it. It only shows
  // when there is something to reveal, so the first and last lines are never dimmed.
  const updateEdges = useCallback(() => {
    const element = scroller.current;
    if (!element) return;
    const below = element.scrollHeight - element.scrollTop - element.clientHeight;
    element.dataset.moreAbove = String(element.scrollTop > 4);
    element.dataset.moreBelow = String(below > 4);
  }, []);

  const onScroll = () => {
    const element = scroller.current;
    if (!element) return;
    stuckToBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80;
    updateEdges();
  };

  useEffect(() => {
    updateEdges();
    const element = scroller.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      const content = thread.current;
      if (content && stuckToBottom.current) element.scrollTop = element.scrollHeight;
      updateEdges();
    });
    observer.observe(element);
    if (thread.current) observer.observe(thread.current);
    window.addEventListener("resize", updateEdges);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", updateEdges);
    };
  }, [hasThread, updateEdges]);

  // A session opened from the rail starts at its end.
  const firstId = messages[0]?.id;
  useEffect(() => {
    stuckToBottom.current = true;
    const element = scroller.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [firstId]);

  return (
    <div className="scroller" ref={scroller} onScroll={onScroll}>
      {!hasThread ? (
        <div className="empty">
          <span className="glyph-big">
            <Icon name="thread" size="md" />
          </span>
          <h3>Nothing here yet</h3>
          <p>Tap the orb and speak, or write below.</p>
        </div>
      ) : (
        <div className="thread" ref={thread} role="log" aria-live="polite" aria-relevant="additions">
          {messages.map((message) =>
            message.error ? (
              <div key={message.id} className="msg notice" role="alert">
                <p>{errorMessage(message.error)}</p>
                {message.error === "auth" ? (
                  <button type="button" className="text-btn" onClick={() => window.location.reload()}>
                    Reload
                  </button>
                ) : (
                  <>
                    <button type="button" className="text-btn" onClick={onRetry}>
                      Try again
                    </button>
                    {message.error === "upstream" && onStartFresh && (
                      <button type="button" className="text-btn" onClick={onStartFresh}>
                        Start fresh in this session
                      </button>
                    )}
                  </>
                )}
              </div>
            ) : message.role === "assistant" ? (
              <AssistantTurn key={message.id} message={message} onCopy={onCopy} onOpenSettings={onOpenSettings} sources={sources} />
            ) : (
              <div key={message.id} className={`msg user${message.voice ? " dictated" : ""}`}>
                {message.voice && (
                  <span className="via" role="img" aria-label="Said by voice">
                    <Icon name="mic" />
                  </span>
                )}
                <Markdown text={message.text} />
              </div>
            ),
          )}
          {waiting && (
            <div className="msg assistant typing" role="status" aria-label="Savant is writing">
              <span className="dots" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
              {elapsed >= 3 && <span className="elapsed">Thinking · {elapsed} s</span>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
