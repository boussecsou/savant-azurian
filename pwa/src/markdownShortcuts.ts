/**
 * Markdown shortcuts for the composer. Pure string edits so they can be tested
 * without a DOM: the caller applies the result to its textarea and restores the
 * selection it returns.
 */

export type MarkdownShortcut = "bold" | "italic" | "code";

export const MARKERS: Record<MarkdownShortcut, string> = {
  bold: "**",
  italic: "*",
  code: "`",
};

export interface EditState {
  value: string;
  start: number;
  end: number;
}

export function applyMarkdownShortcut(state: EditState, shortcut: MarkdownShortcut): EditState {
  const marker = MARKERS[shortcut];
  const size = marker.length;
  const start = Math.max(0, Math.min(state.start, state.value.length));
  const end = Math.max(start, Math.min(state.end, state.value.length));
  const before = state.value.slice(0, start);
  const after = state.value.slice(end);
  const selected = state.value.slice(start, end);

  // Markers already sit just outside the selection: toggle them off.
  if (before.endsWith(marker) && after.startsWith(marker)) {
    const from = start - size;
    return {
      value: before.slice(0, -size) + selected + after.slice(size),
      start: from,
      end: from + selected.length,
    };
  }

  // The selection already includes its markers: strip them.
  if (selected.length >= size * 2 && selected.startsWith(marker) && selected.endsWith(marker)) {
    const inner = selected.slice(size, -size);
    return { value: before + inner + after, start, end: start + inner.length };
  }

  return {
    value: before + marker + selected + marker + after,
    start: start + size,
    end: end + size,
  };
}
