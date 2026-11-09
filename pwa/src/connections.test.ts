import { describe, expect, it } from "vitest";
import { bannerKind, needsAttention, notionView, outlookView } from "./connections";

describe("notionView", () => {
  it("maps the five real states, with the right action", () => {
    expect(notionView("connected")).toMatchObject({ state: "connected", tone: "ok" });
    expect(notionView("connected").action).toBeUndefined();
    expect(notionView("disconnected")).toMatchObject({ label: "Not connected", action: "Connect" });
    expect(notionView("waiting")).toMatchObject({ label: "Connecting…", action: "Reopen" });
    expect(notionView("unavailable")).toMatchObject({ tone: "err", action: "Retry" });
    expect(notionView("unknown")).toMatchObject({ state: "checking", label: "Checking…" });
    expect(notionView("unknown").action).toBeUndefined();
  });
});

describe("outlookView", () => {
  it("is connected, needs sign-in, or is unknown", () => {
    expect(outlookView("connected").state).toBe("connected");
    expect(outlookView("disconnected").action).toBe("Connect");
    expect(outlookView("unknown").label).toBe("Not checked yet");
  });
});

describe("needsAttention", () => {
  it("flags a Notion that is down, not one still being checked or opened", () => {
    expect(needsAttention("disconnected", "unknown", false)).toBe(true);
    expect(needsAttention("unavailable", "unknown", false)).toBe(true);
    expect(needsAttention("unknown", "unknown", false)).toBe(false);
    expect(needsAttention("waiting", "unknown", false)).toBe(false);
    expect(needsAttention("connected", "unknown", false)).toBe(false);
  });

  it("looks at Outlook only when it is enabled", () => {
    expect(needsAttention("connected", "disconnected", false)).toBe(false);
    expect(needsAttention("connected", "disconnected", true)).toBe(true);
    expect(needsAttention("connected", "unknown", true)).toBe(false);
  });
});

describe("bannerKind", () => {
  it("shows the most serious problem first", () => {
    expect(bannerKind({ authDenied: true, online: false, notion: "unavailable" })).toBe("auth");
    expect(bannerKind({ authDenied: false, online: false, notion: "unavailable" })).toBe("offline");
    expect(bannerKind({ authDenied: false, online: true, notion: "unavailable" })).toBe("tool");
    expect(bannerKind({ authDenied: false, online: true, notion: "connected" })).toBeNull();
  });
});
