import { Icon } from "../Icon";

interface Props {
  mobile: "stage" | "thread";
  drawerOpen: boolean;
  /** The thread alone: there is no voice view to go to. */
  chatOnly?: boolean;
  onMobile: (view: "stage" | "thread") => void;
  onDrawer: () => void;
}

/** The bottom bar of narrow screens: Voice, Thread and Sessions (the rail as a drawer). */
export function MobileNav({ mobile, drawerOpen, chatOnly, onMobile, onDrawer }: Props) {
  return (
    <nav className="mnav" aria-label="Sections" data-chat-only={chatOnly ? "on" : undefined}>
      {!chatOnly && (
        <button type="button" className="press" aria-current={mobile === "stage" && !drawerOpen ? "true" : undefined} onClick={() => onMobile("stage")}>
          <Icon name="orb" size="md" />
          Voice
        </button>
      )}
      <button type="button" className="press" aria-current={(chatOnly || mobile === "thread") && !drawerOpen ? "true" : undefined} onClick={() => onMobile("thread")}>
        <Icon name="thread" size="md" />
        Thread
      </button>
      <button type="button" className="press" aria-current={drawerOpen ? "true" : undefined} onClick={onDrawer}>
        <Icon name="menu" size="md" />
        Sessions
      </button>
    </nav>
  );
}
