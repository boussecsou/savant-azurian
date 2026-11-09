import type { DragEvent, ReactNode } from "react";
import { Icon } from "../Icon";

interface Props {
  title: string;
  messageCount: number;
  onCopySession: () => void;
  /** Files dropped anywhere on the thread go to the project's sources; `veil` is shown while dragging. */
  drop?: { onDragOver: (event: DragEvent) => void; onDragLeave: (event: DragEvent) => void; onDrop: (event: DragEvent) => void };
  veil?: ReactNode;
  children: ReactNode;
}

/** The right column: the thread of the open session with its composer. (The Canvas is off for now.) */
export function Dock({ title, messageCount, onCopySession, drop, veil, children }: Props) {
  return (
    <section className="dock" id="dock" aria-label="Conversation" data-over={veil ? "" : undefined} {...drop}>
      <div className="dock-inner">
        <div className="panes">
          <div className="pane" data-pane="thread">
            <div className="pane-head">
              <h2>{title}</h2>
              <small>
                {messageCount} message{messageCount === 1 ? "" : "s"}
              </small>
              <button type="button" className="icon-btn sm press" aria-label="Copy session as Markdown" title="Copy session as Markdown" onClick={onCopySession}>
                <Icon name="copy" />
              </button>
            </div>
            {children}
            {veil}
          </div>
        </div>
      </div>
    </section>
  );
}
