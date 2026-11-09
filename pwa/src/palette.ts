export interface Command {
  id: string;
  title: string;
  /** "Action", "Project", "Session"…: shown on the right and searched too. */
  kind: string;
  run: () => void;
}

export const PALETTE_MAX = 9;

/** Every word typed must appear in the title or the kind. No query lists the first commands. */
export function filterCommands(commands: readonly Command[], query: string, max = PALETTE_MAX): Command[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return commands.slice(0, max);
  return commands
    .filter((command) => {
      const haystack = `${command.title} ${command.kind}`.toLowerCase();
      return words.every((word) => haystack.includes(word));
    })
    .slice(0, max);
}
