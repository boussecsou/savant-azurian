import { describe, expect, it } from "vitest";
import { applyMarkdownShortcut } from "./markdownShortcuts";

describe("applyMarkdownShortcut", () => {
  it("wraps the selection and keeps it selected", () => {
    expect(applyMarkdownShortcut({ value: "un mot", start: 3, end: 6 }, "bold")).toEqual({
      value: "un **mot**",
      start: 5,
      end: 8,
    });
    expect(applyMarkdownShortcut({ value: "un mot", start: 3, end: 6 }, "italic")).toEqual({
      value: "un *mot*",
      start: 4,
      end: 7,
    });
    expect(applyMarkdownShortcut({ value: "un mot", start: 3, end: 6 }, "code")).toEqual({
      value: "un `mot`",
      start: 4,
      end: 7,
    });
  });

  it("inserts the markers and puts the caret between them without a selection", () => {
    expect(applyMarkdownShortcut({ value: "", start: 0, end: 0 }, "bold")).toEqual({
      value: "****",
      start: 2,
      end: 2,
    });
    expect(applyMarkdownShortcut({ value: "abc", start: 1, end: 1 }, "code")).toEqual({
      value: "a``bc",
      start: 2,
      end: 2,
    });
  });

  it("removes the markers when the selection is already wrapped", () => {
    expect(applyMarkdownShortcut({ value: "un **mot** ici", start: 5, end: 8 }, "bold")).toEqual({
      value: "un mot ici",
      start: 3,
      end: 6,
    });
  });

  it("removes the markers when they are part of the selection", () => {
    expect(applyMarkdownShortcut({ value: "un **mot** ici", start: 3, end: 10 }, "bold")).toEqual({
      value: "un mot ici",
      start: 3,
      end: 6,
    });
  });

  it("clamps an out-of-range selection instead of dropping characters", () => {
    expect(applyMarkdownShortcut({ value: "abc", start: -4, end: 99 }, "italic")).toEqual({
      value: "*abc*",
      start: 1,
      end: 4,
    });
  });

  it("keeps parentheses and accents intact", () => {
    expect(applyMarkdownShortcut({ value: "déjà (vu)", start: 5, end: 9 }, "italic")).toEqual({
      value: "déjà *(vu)*",
      start: 6,
      end: 10,
    });
  });
});
