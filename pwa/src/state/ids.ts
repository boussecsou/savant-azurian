/**
 * Identifiers worth copying: UUIDs, 32-hex ids (Notion), Foundry response ids, operation digests and
 * 16-hex correlation ids. They are shown as small copyable chips in the thread.
 */
const SOURCE = String.raw`\b(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[0-9a-fA-F]{32}|caresp_[A-Za-z0-9]{8,}|op:[0-9a-fA-F]{8,}|[0-9a-fA-F]{16})\b`;

/** A fresh pattern each time: a shared global RegExp keeps state between calls (lastIndex). */
export function idPattern(): RegExp {
  return new RegExp(SOURCE, "g");
}

export type TextRun = { id: false; text: string } | { id: true; text: string };

/** Cut a text into plain runs and identifier runs, in order. */
export function splitIds(text: string): TextRun[] {
  const runs: TextRun[] = [];
  let last = 0;
  for (const match of text.matchAll(idPattern())) {
    const start = match.index ?? 0;
    if (start > last) runs.push({ id: false, text: text.slice(last, start) });
    runs.push({ id: true, text: match[0] });
    last = start + match[0].length;
  }
  if (last < text.length) runs.push({ id: false, text: text.slice(last) });
  return runs;
}

/** Identifiers in a Markdown text, in order. Fenced code blocks are left out: they have their own Copy button. */
export function extractIds(markdown: string): string[] {
  const outside = markdown.replace(/```[\s\S]*?(?:```|$)/g, " ");
  return Array.from(outside.matchAll(idPattern()), (m) => m[0]);
}

/** The most recent distinct identifiers of a conversation, newest first. */
export function recentIds(texts: readonly string[], limit = 4): string[] {
  const seen: string[] = [];
  for (let i = texts.length - 1; i >= 0 && seen.length < limit; i--) {
    const ids = extractIds(texts[i]);
    for (let j = ids.length - 1; j >= 0 && seen.length < limit; j--) {
      if (!seen.includes(ids[j])) seen.push(ids[j]);
    }
  }
  return seen;
}
