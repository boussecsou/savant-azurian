import type { ReactNode } from "react";
import { Icon } from "../Icon";

interface Props {
  onCollapse: () => void;
  onPalette: () => void;
  /** The project button and its list: the scope of what follows. */
  switcher: ReactNode;
  sessions: ReactNode;
  /** The active project's sources, when documents are on. */
  sources?: ReactNode;
}

/** The left column: brand, the project, its sessions, its sources, and the owner. */
export function Rail({ onCollapse, onPalette, switcher, sessions, sources }: Props) {
  return (
    <aside className="rail" id="rail" aria-label="Project and sessions">
      <div className="rail-inner">
        <div className="rail-head">
          <div className="brand">
            <img src="/icons/icon-192.png" alt="" width="24" height="24" />
            Savant
          </div>
          <button type="button" className="icon-btn press" aria-label="Hide sidebar" onClick={onCollapse}>
            <Icon name="rail" size="md" />
          </button>
        </div>
        {switcher}
        <div className="rail-panels">{sessions}</div>
        {sources}
        <div className="rail-foot">
          <span className="avatar" aria-hidden="true">
            A
          </span>
          <div className="grow">
            Owner
            <small>Entra ID · single user</small>
          </div>
          <button type="button" className="icon-btn sm press" aria-label="Open command palette" title="Command palette (Ctrl+K)" onClick={onPalette}>
            <Icon name="cmd" />
          </button>
        </div>
      </div>
    </aside>
  );
}
