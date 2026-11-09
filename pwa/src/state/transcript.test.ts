import { describe, expect, it } from "vitest";
import { sessionToMarkdown } from "./transcript";

describe("sessionToMarkdown", () => {
  it("labels speakers, marks dictated messages and skips error notices", () => {
    const text = sessionToMarkdown("Weekly plan", [
      { id: "1", role: "user", text: "What is on today?", voice: true },
      { id: "2", role: "assistant", text: "Two meetings." },
      { id: "3", role: "assistant", text: "", error: "network" },
      { id: "4", role: "user", text: "Thanks" },
    ]);
    expect(text).toBe("# Weekly plan\n\n**You** (voice): What is on today?\n\n**Savant**: Two meetings.\n\n**You**: Thanks\n");
  });
});
