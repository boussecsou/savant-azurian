/** Rules of the composer's keyboard and its "/" menu: pure, so they can be tested. */

export type EnterAction = "send" | "newline" | "none";

/**
 * What Enter does. Normal mode: Enter sends, Shift+Enter adds a line. Technical mode (pasting logs
 * and code): Enter adds a line. Ctrl/⌘+Enter sends in both. Nothing happens while an input method is composing.
 */
export function enterAction(event: { shift: boolean; mod: boolean; composing: boolean }, tech: boolean): EnterAction {
  if (event.composing) return "none";
  if (event.mod) return "send";
  if (tech) return "newline";
  return event.shift ? "newline" : "send";
}

export interface SlashCommand {
  name: string;
  hint: string;
  /** Text that replaces the "/word", and where the cursor goes inside it (default: the end). */
  insert: string;
  cursor?: number;
}

export const SLASH_COMMANDS: readonly SlashCommand[] = [
  { name: "/id", hint: "Look up an ID", insert: "Look up an ID: " },
  { name: "/code", hint: "Insert a code block", insert: "```\n\n```", cursor: 4 },
];

/** The word typed after "/" when the whole content is exactly "/word", else null. */
export function slashQuery(text: string): string | null {
  const match = /^\/(\w*)$/.exec(text);
  return match ? match[1] : null;
}

export function matchSlash(text: string): SlashCommand[] {
  const query = slashQuery(text);
  if (query === null) return [];
  return SLASH_COMMANDS.filter((command) => command.name.slice(1).startsWith(query.toLowerCase()));
}

export function applySlash(command: SlashCommand): { value: string; cursor: number } {
  return { value: command.insert, cursor: command.cursor ?? command.insert.length };
}

export const COUNTER_SHOW = 6400;
export const COUNTER_WARN = 7600;
export const MAX_LENGTH = 8000;
