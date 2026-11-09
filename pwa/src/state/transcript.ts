import type { ChatMessage } from "../chat";

/** A session as Markdown, for the clipboard: who spoke, whether it was dictated, and what was said. */
export function sessionToMarkdown(title: string, messages: readonly ChatMessage[]): string {
  const lines = [`# ${title}`, ""];
  for (const message of messages) {
    if (message.error) continue;
    const who = message.role === "user" ? "**You**" : "**Savant**";
    const via = message.voice ? " (voice)" : "";
    lines.push(`${who}${via}: ${message.text.trim()}`, "");
  }
  return lines.join("\n").trimEnd() + "\n";
}
