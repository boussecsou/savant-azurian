import type { NotionState } from "./useNotion";
import type { OutlookState } from "./useOutlook";

export type Tone = "" | "ok" | "warn" | "err";

export interface ConnectionView {
  /** Drives the card's look: connected / disconnected / unavailable / waiting / checking / managed / planned. */
  state: "connected" | "disconnected" | "unavailable" | "waiting" | "checking";
  label: string;
  tone: Tone;
  /** The button on the card, if any. */
  action?: "Connect" | "Reopen" | "Retry";
}

/** What the settings card says about Notion. "Expired" does not exist: the gateway only says connected or not. */
export function notionView(state: NotionState): ConnectionView {
  switch (state) {
    case "connected":
      return { state: "connected", label: "Connected", tone: "ok" };
    case "disconnected":
      return { state: "disconnected", label: "Not connected", tone: "warn", action: "Connect" };
    case "waiting":
      return { state: "waiting", label: "Connecting…", tone: "", action: "Reopen" };
    case "unavailable":
      return { state: "unavailable", label: "Unavailable", tone: "err", action: "Retry" };
    default:
      return { state: "checking", label: "Checking…", tone: "" };
  }
}

export function outlookView(state: OutlookState): ConnectionView {
  if (state === "connected") return { state: "connected", label: "Connected", tone: "ok" };
  if (state === "disconnected") return { state: "disconnected", label: "Sign-in needed", tone: "warn", action: "Connect" };
  return { state: "checking", label: "Not checked yet", tone: "" };
}

/** The dot on the Settings icon: a connection that is down, not one that is still being checked or opened. */
export function needsAttention(notion: NotionState, outlook: OutlookState, outlookEnabled: boolean): boolean {
  if (notion === "disconnected" || notion === "unavailable") return true;
  return outlookEnabled && outlook === "disconnected";
}

export type BannerKind = "auth" | "offline" | "tool" | null;

/** One banner at a time, most serious first: access, then the network, then a tool. */
export function bannerKind(opts: { authDenied: boolean; online: boolean; notion: NotionState }): BannerKind {
  if (opts.authDenied) return "auth";
  if (!opts.online) return "offline";
  if (opts.notion === "unavailable") return "tool";
  return null;
}
