import { useEffect, useRef, type ReactNode } from "react";
import { usePresence } from "../../hooks/usePresence";
import type { Project } from "../../state/workspace";
import { Icon } from "../Icon";

interface Props {
  project: Project;
  sessionCount: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The project list (with its create form), shown in the popover. */
  children: ReactNode;
}

const EXIT_MS = 150;

/**
 * The project is the scope of everything below it (its sessions, its sources), so it is chosen once, at the
 * top of the rail, instead of in a tab of its own. The list opens from the button it belongs to and grows
 * from that corner (a popover, unlike a modal, is anchored to its trigger).
 */
export function ProjectSwitcher({ project, sessionCount, open, onOpenChange, children }: Props) {
  const root = useRef<HTMLDivElement>(null);
  const { mounted, shown } = usePresence(open, EXIT_MS);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Element | null;
      // The project's own "…" menu is a portal: a click in it is still a click in the switcher.
      if (target && (root.current?.contains(target) || target.closest(".menu"))) return;
      onOpenChange(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || document.querySelector(".menu")) return;
      event.stopPropagation();
      onOpenChange(false);
      root.current?.querySelector<HTMLElement>(".pswitch-btn")?.focus();
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open, onOpenChange]);

  return (
    <div className="pswitch" ref={root}>
      <button type="button" className="pswitch-btn press" aria-haspopup="true" aria-expanded={open} aria-controls="pswitch-pop" onClick={() => onOpenChange(!open)}>
        <span className="dot" style={{ ["--c" as string]: project.color }} />
        <span className="pswitch-name">
          <b>{project.name}</b>
          <small>
            {sessionCount} session{sessionCount === 1 ? "" : "s"}
          </small>
        </span>
        <Icon name="chevron" />
      </button>
      {mounted && (
        <div className="pswitch-pop" id="pswitch-pop" data-open={shown ? "" : undefined} aria-label="Projects">
          {children}
        </div>
      )}
    </div>
  );
}
