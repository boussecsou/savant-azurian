import { describe, expect, it } from "vitest";
import { filterCommands, type Command } from "./palette";

const make = (id: string, title: string, kind: string): Command => ({ id, title, kind, run: () => undefined });
const commands = [
  make("a", "New session", "Action"),
  make("b", "Open settings", "Action"),
  make("c", "Savant Azurian 2", "Project"),
  make("d", "Easy Auth debugging", "Session · Savant Azurian 2"),
];

describe("filterCommands", () => {
  it("lists the first commands without a query, capped", () => {
    expect(filterCommands(commands, "  ", 2).map((c) => c.id)).toEqual(["a", "b"]);
  });

  it("requires every word, in the title or the kind, ignoring case", () => {
    expect(filterCommands(commands, "SESSION new").map((c) => c.id)).toEqual(["a"]);
    expect(filterCommands(commands, "azurian").map((c) => c.id)).toEqual(["c", "d"]);
    expect(filterCommands(commands, "project savant").map((c) => c.id)).toEqual(["c"]);
    expect(filterCommands(commands, "nothing")).toEqual([]);
  });
});
