import { describe, expect, it } from "vitest";
import { outlookStateAfterTool, readOutlook } from "./useOutlook";

describe("outlookStateAfterTool", () => {
  it("treats a finished Outlook call, behind the toolbox prefix or not, as connected", () => {
    expect(outlookStateAfterTool("outlook-sa2___outlook_GetEmails")).toBe("connected");
    expect(outlookStateAfterTool("outlook_SendEmailV2")).toBe("connected");
  });

  it("treats an Outlook call that only returned a sign-in link as not connected", () => {
    expect(outlookStateAfterTool("outlook-sa2___outlook_GetEmails", true)).toBe("disconnected");
    expect(outlookStateAfterTool("notion-search", true)).toBeNull();
  });

  it("treats the sign-in tool as not connected", () => {
    expect(outlookStateAfterTool("oauth_consent_required")).toBe("disconnected");
  });

  it("ignores every other tool", () => {
    expect(outlookStateAfterTool("notion-search")).toBeNull();
    expect(outlookStateAfterTool("call_tool")).toBeNull();
    expect(outlookStateAfterTool(undefined)).toBeNull();
  });
});

describe("readOutlook", () => {
  it("reads a saved state and falls back to unknown", () => {
    expect(readOutlook({ getItem: () => "connected" })).toBe("connected");
    expect(readOutlook({ getItem: () => "disconnected" })).toBe("disconnected");
    expect(readOutlook({ getItem: () => "garbage" })).toBe("unknown");
    expect(readOutlook({ getItem: () => null })).toBe("unknown");
    expect(readOutlook({ getItem: () => { throw new Error("blocked"); } })).toBe("unknown");
    expect(readOutlook(undefined)).toBe("unknown");
  });
});
