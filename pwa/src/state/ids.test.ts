import { describe, expect, it } from "vitest";
import { extractIds, recentIds, splitIds } from "./ids";

const UUID = "3d1eba09-656f-8182-a23d-fdc5b5428fa8";
const HEX32 = "3d1eba09656f8182a23dfdc5b5428fa8";
const CORR = "0d4aa372e12872c7";

describe("extractIds", () => {
  it("finds each kind of identifier", () => {
    const text = `uuid ${UUID}, notion ${HEX32}, run caresp_AbC12345xyz, digest op:deadbeef01, correlation ${CORR}.`;
    expect(extractIds(text)).toEqual([UUID, HEX32, "caresp_AbC12345xyz", "op:deadbeef01", CORR]);
  });

  it("ignores fenced code blocks but not inline code", () => {
    const text = "see `" + CORR + "`\n```\n" + UUID + "\n```\nand " + HEX32;
    expect(extractIds(text)).toEqual([CORR, HEX32]);
  });

  it("ignores an unclosed fence while a reply is still streaming", () => {
    expect(extractIds("before\n```\n" + UUID)).toEqual([]);
  });

  it("does not match a longer hex string or ordinary words", () => {
    expect(extractIds("a".repeat(20))).toEqual([]);
    expect(extractIds("abcdefghijklmnop")).toEqual([]);
  });

  it("is stateless between calls", () => {
    expect(extractIds(CORR)).toEqual([CORR]);
    expect(extractIds(CORR)).toEqual([CORR]);
  });
});

describe("splitIds", () => {
  it("keeps the text around each identifier", () => {
    expect(splitIds(`id ${CORR} done`)).toEqual([
      { id: false, text: "id " },
      { id: true, text: CORR },
      { id: false, text: " done" },
    ]);
    expect(splitIds("nothing here")).toEqual([{ id: false, text: "nothing here" }]);
    expect(splitIds("")).toEqual([]);
  });
});

describe("recentIds", () => {
  it("returns the last distinct ids, newest first, capped", () => {
    const a = "1".repeat(16);
    const b = "2".repeat(16);
    const c = "3".repeat(16);
    const d = "4".repeat(16);
    const e = "5".repeat(16);
    expect(recentIds([a, `${b} ${a}`, c, `${d} ${e}`])).toEqual([e, d, c, a]);
    expect(recentIds([a, a, a])).toEqual([a]);
    expect(recentIds([])).toEqual([]);
  });
});
