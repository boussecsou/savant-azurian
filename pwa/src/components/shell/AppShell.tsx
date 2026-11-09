import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { BootPhase } from "../../boot";

interface Props {
  railOpen: boolean;
  focus: boolean;
  /** The thread alone: the voice stage is hidden. */
  chatOnly: boolean;
  drawer: boolean;
  mobile: "stage" | "thread";
  /** Start-up phase: the interface arrives in a short cascade once the splash is gone. */
  boot: BootPhase;
  voiceActive: boolean;
  reducedMotion: boolean;
  onCloseDrawer: () => void;
  rail: ReactNode;
  stage: ReactNode;
  dock: ReactNode;
}

const FADE_MS = 160;

/**
 * Folding the side panels is done in two steps so layout is never animated: the panel fades and
 * slides out (opacity and transform), then its column drops to zero at once and the orb glides to
 * its new place (FLIP, a transform). Opening is the reverse. With reduced motion, all of it is instant.
 */
function useShellLayout(wantRail: boolean, wantDock: boolean, reduced: boolean, app: React.RefObject<HTMLDivElement | null>) {
  const [layout, setLayout] = useState({ rail: wantRail, dock: wantDock });
  const [vis, setVis] = useState({ rail: wantRail, dock: wantDock });
  const layoutRef = useRef(layout);
  layoutRef.current = layout;
  const before = useRef<DOMRect | null>(null);
  const orb = () => app.current?.querySelector<HTMLElement>(".orb-wrap") ?? null;

  useEffect(() => {
    const hiding = (!wantRail && layoutRef.current.rail) || (!wantDock && layoutRef.current.dock);
    setVis((v) => ({ rail: v.rail && wantRail, dock: v.dock && wantDock }));
    const timer = window.setTimeout(
      () => {
        if (layoutRef.current.rail === wantRail && layoutRef.current.dock === wantDock) return;
        before.current = orb()?.getBoundingClientRect() ?? null;
        setLayout({ rail: wantRail, dock: wantDock });
      },
      hiding && !reduced ? FADE_MS : 0,
    );
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wantRail, wantDock, reduced]);

  useLayoutEffect(() => {
    const element = orb();
    const first = before.current;
    before.current = null;
    if (element && first && !reduced) {
      const last = element.getBoundingClientRect();
      const dx = first.left - last.left;
      const dy = first.top - last.top;
      if (Math.abs(dx) >= 1 || Math.abs(dy) >= 1) {
        element.animate([{ translate: `${dx}px ${dy}px` }, { translate: "0 0" }], { duration: 300, easing: "cubic-bezier(0.77, 0, 0.175, 1)" });
      }
    }
    const frame = requestAnimationFrame(() => setVis({ rail: layout.rail, dock: layout.dock }));
    return () => cancelAnimationFrame(frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout, reduced]);

  return { layout, vis };
}

/** Three zones: rail (sessions and projects), stage (the orb), dock (the thread). */
export function AppShell({ railOpen, focus, chatOnly, drawer, mobile, boot, voiceActive, reducedMotion, onCloseDrawer, rail, stage, dock }: Props) {
  const app = useRef<HTMLDivElement>(null);
  const { layout, vis } = useShellLayout(railOpen && !focus, !focus, reducedMotion, app);
  return (
    <div
      ref={app}
      className="app"
      data-rail={layout.rail ? "open" : "closed"}
      data-rail-vis={vis.rail ? "shown" : "hidden"}
      data-dock-vis={vis.dock ? "shown" : "hidden"}
      data-focus={focus && !layout.dock ? "on" : "off"}
      data-chat-only={chatOnly ? "on" : "off"}
      data-voice-active={voiceActive ? "true" : "false"}
      data-mobile={mobile}
      data-boot={boot}
      data-drawer={drawer ? "open" : "closed"}
    >
      {rail}
      <div className="scrim" onClick={onCloseDrawer} aria-hidden="true" />
      {stage}
      {dock}
    </div>
  );
}
