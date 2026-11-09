import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { IdChip } from "./components/IdChip";
import { splitIds } from "./state/ids";

/**
 * A small hand-written Markdown subset for chat messages: headings, paragraphs,
 * blockquotes, nested lists, task lists, GFM tables, rules, fenced code, inline
 * code, bold, italic, strikethrough and http(s) links.
 *
 * Everything is built as React nodes, never as HTML strings, so message text
 * cannot inject markup. The parser also has to survive half-written Markdown,
 * because replies are rendered while they stream: an unclosed fence, a lone
 * "**" or a table header without its delimiter stay plain text until complete.
 */

/** Identifiers inside a text run become copyable chips; everything else stays text. */
function withIds(text: string, key: () => number): ReactNode[] {
  return splitIds(text).map((run) => (run.id ? <IdChip key={`id-${key()}`} id={run.text} /> : run.text));
}

const ESCAPABLE = "\\`*_{}[]()#+-.!|~>";

function safeUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function runLength(text: string, start: number, char: string): number {
  let end = start;
  while (text[end] === char) end++;
  return end - start;
}

/** GFM strips one leading and one trailing space when a code span has both. */
function stripCodePadding(value: string): string {
  if (value.length > 2 && value.startsWith(" ") && value.endsWith(" ") && value.trim()) {
    return value.slice(1, -1);
  }
  return value;
}

function parseLink(text: string, start: number): { label: string; href: string; end: number } | null {
  if (text[start] !== "[") return null;
  let depth = 0;
  let index = start;
  for (; index < text.length; index++) {
    const char = text[index];
    if (char === "\n") return null;
    if (char === "[") depth++;
    else if (char === "]") {
      depth--;
      if (depth === 0) break;
    }
  }
  if (index >= text.length || text[index + 1] !== "(") return null;
  const label = text.slice(start + 1, index);

  let close = index + 2;
  let parens = 1;
  for (; close < text.length; close++) {
    const char = text[close];
    if (char === "\n") return null;
    if (char === "(") parens++;
    else if (char === ")") {
      parens--;
      if (parens === 0) break;
    }
  }
  if (close >= text.length) return null;

  // An optional title ("...") follows the address; only the address is used.
  const target = text
    .slice(index + 2, close)
    .trim()
    .split(/\s+/)[0]
    ?.replace(/^<|>$/g, "");
  if (!target) return null;
  return { label, href: target, end: close + 1 };
}

/** Underscores only open and close emphasis at word boundaries, so snake_case stays literal. */
function emphasisBoundary(text: string, index: number): boolean {
  const before = index > 0 ? text[index - 1] : "";
  return before === "" || !/[\p{L}\p{N}]/u.test(before);
}

function findEmphasisClose(text: string, from: number, marker: string, char: string): number {
  let index = text.indexOf(marker, from);
  while (index !== -1) {
    const between = text.slice(from, index);
    const valid = between.length > 0 && !between.includes("\n") && !/^\s+$/.test(between);
    if (valid) {
      if (char !== "_") {
        // "**a *b***": the closing run is three stars, and one of them closes the inner emphasis.
        const run = runLength(text, index, "*");
        const singles = (between.match(/\*/g) ?? []).length;
        if (marker === "**" && run % 2 === 1 && singles % 2 === 1) return index + 1;
        return index;
      }
      const after = text[index + marker.length] ?? "";
      if (after === "" || !/[\p{L}\p{N}]/u.test(after)) return index;
    }
    index = text.indexOf(marker, index + marker.length);
  }
  return -1;
}

function urlStartsAt(text: string, index: number): boolean {
  if (!/^https?:\/\//i.test(text.slice(index))) return false;
  const before = index > 0 ? text[index - 1] : "";
  return before === "" || !/[A-Za-z0-9]/.test(before);
}

export function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let key = 0;
  let plain = "";

  const flush = () => {
    if (plain) {
      nodes.push(...withIds(plain, () => key++));
      plain = "";
    }
  };
  const push = (node: ReactNode) => {
    flush();
    nodes.push(node);
  };

  let index = 0;
  while (index < text.length) {
    const char = text[index];

    // A backslash escapes the next punctuation character.
    if (char === "\\" && index + 1 < text.length && ESCAPABLE.includes(text[index + 1])) {
      plain += text[index + 1];
      index += 2;
      continue;
    }

    if (char === "`") {
      const run = runLength(text, index, "`");
      const fence = "`".repeat(run);
      const close = text.indexOf(fence, index + run);
      if (close > index + run) {
        push(<code key={key++}>{withIds(stripCodePadding(text.slice(index + run, close)), () => key++)}</code>);
        index = close + run;
        continue;
      }
      // Unclosed run: keep it literal instead of swallowing what follows.
      plain += fence;
      index += run;
      continue;
    }

    if (char === "!") {
      const image = parseLink(text, index + 1);
      if (image) {
        // Images are not fetched: only their description is kept.
        plain += image.label;
        index = image.end;
        continue;
      }
    }

    if (char === "[") {
      const link = parseLink(text, index);
      const url = link ? safeUrl(link.href) : null;
      if (link && url) {
        push(
          <a key={key++} href={url} target="_blank" rel="noopener noreferrer">
            {renderInline(link.label)}
          </a>,
        );
        index = link.end;
        continue;
      }
      // An incomplete or refused link stays as written, and the scan moves on.
      plain += char;
      index++;
      continue;
    }

    if (char === "*" || char === "_") {
      const strong = text[index + 1] === char;
      const marker = strong ? char + char : char;
      const opens = strong || emphasisBoundary(text, index);
      if (opens) {
        const close = findEmphasisClose(text, index + marker.length, marker, char);
        if (close !== -1) {
          const inside = renderInline(text.slice(index + marker.length, close));
          push(strong ? <strong key={key++}>{inside}</strong> : <em key={key++}>{inside}</em>);
          index = close + marker.length;
          continue;
        }
      }
      plain += char;
      index++;
      continue;
    }

    if (char === "~" && text[index + 1] === "~") {
      const close = text.indexOf("~~", index + 2);
      if (close > index + 2) {
        push(<del key={key++}>{renderInline(text.slice(index + 2, close))}</del>);
        index = close + 2;
        continue;
      }
      plain += "~~";
      index += 2;
      continue;
    }

    if ((char === "h" || char === "H") && urlStartsAt(text, index)) {
      const match = /^https?:\/\/[^\s<>"'`]+/i.exec(text.slice(index));
      if (match) {
        // Trailing punctuation belongs to the sentence, not to the address.
        const raw = match[0];
        const trimmed = raw.replace(/[.,;:!?]+$/, "");
        const url = safeUrl(trimmed);
        if (url) {
          push(
            <a key={key++} href={url} target="_blank" rel="noopener noreferrer">
              {trimmed}
            </a>,
          );
          if (trimmed.length < raw.length) plain += raw.slice(trimmed.length);
          index += raw.length;
          continue;
        }
      }
    }

    plain += char;
    index++;
  }

  flush();
  return nodes;
}

function CodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const copy = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(code);
      } else {
        const area = document.createElement("textarea");
        area.value = code;
        area.setAttribute("readonly", "");
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        area.remove();
      }
      setCopied(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard blocked: the code stays selectable by hand.
    }
  };

  return (
    <div className="code-block">
      <div className="code-head">
        <span className="code-lang">{language || "texte"}</span>
        <button type="button" className="code-copy" onClick={() => void copy()}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}

const FENCE = /^\s{0,3}(`{3,}|~{3,})\s*([^`~]*)$/;
const HEADING = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const RULE = /^\s{0,3}(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})$/;
const QUOTE = /^\s{0,3}>/;
const LIST = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
const TASK = /^\[([ xX])\]\s+(.*)$/;
const DELIMITER_CELL = /^:?-{1,}:?$/;

function indentOf(line: string): number {
  return line.replace(/\t/g, "    ").length - line.replace(/\t/g, "    ").trimStart().length;
}

function dedent(lines: string[], amount: number): string[] {
  const present = lines.filter((line) => line.trim());
  const common = Math.min(amount, ...present.map(indentOf));
  return lines.map((line) => (line.trim() ? line.slice(common) : ""));
}

function splitRow(line: string): string[] {
  let value = line.trim();
  if (value.startsWith("|")) value = value.slice(1);
  if (value.endsWith("|") && !value.endsWith("\\|")) value = value.slice(0, -1);
  const cells: string[] = [];
  let current = "";
  for (let index = 0; index < value.length; index++) {
    if (value[index] === "\\" && value[index + 1] === "|") {
      current += "|";
      index++;
      continue;
    }
    if (value[index] === "|") {
      cells.push(current);
      current = "";
      continue;
    }
    current += value[index];
  }
  cells.push(current);
  return cells.map((cell) => cell.trim());
}

function tableAt(lines: string[], start: number): { node: ReactNode; end: number } | null {
  const header = lines[start];
  if (!header.includes("|")) return null;
  const delimiterLine = lines[start + 1];
  if (!delimiterLine || !delimiterLine.includes("|")) return null;

  const head = splitRow(header);
  const delimiter = splitRow(delimiterLine);
  if (delimiter.length !== head.length) return null;

  const alignments: ("" | "left" | "center" | "right")[] = [];
  for (const cell of delimiter) {
    if (!DELIMITER_CELL.test(cell)) return null;
    const left = cell.startsWith(":");
    const right = cell.endsWith(":");
    alignments.push(left && right ? "center" : right ? "right" : left ? "left" : "");
  }

  const rows: string[][] = [];
  let index = start + 2;
  while (index < lines.length && lines[index].trim() && lines[index].includes("|")) {
    const row = splitRow(lines[index]);
    while (row.length < head.length) row.push("");
    rows.push(row.slice(0, head.length));
    index++;
  }

  const cell = (value: string, column: number, tag: "th" | "td") => {
    const align = alignments[column];
    return tag === "th" ? (
      <th key={column} scope="col" style={align ? { textAlign: align } : undefined}>
        {renderInline(value)}
      </th>
    ) : (
      <td key={column} style={align ? { textAlign: align } : undefined}>
        {renderInline(value)}
      </td>
    );
  };

  return {
    node: (
      <div className="table-wrap">
        <table>
          <thead>
            <tr>{head.map((value, column) => cell(value, column, "th"))}</tr>
          </thead>
          <tbody>
            {rows.map((row, line) => (
              <tr key={line}>{row.map((value, column) => cell(value, column, "td"))}</tr>
            ))}
          </tbody>
        </table>
      </div>
    ),
    end: index,
  };
}

function listAt(lines: string[], start: number, depth: number): { node: ReactNode; end: number } | null {
  const first = LIST.exec(lines[start]);
  if (!first) return null;
  const indent = indentOf(first[1]);
  const ordered = /\d/.test(first[2]);
  const items: { text: string; children: string[] }[] = [];
  let index = start;

  while (index < lines.length) {
    const match = LIST.exec(lines[index]);
    if (!match || indentOf(match[1]) !== indent || /\d/.test(match[2]) !== ordered) break;

    const item = { text: match[3], children: [] as string[] };
    index++;

    // Continuation lines and nested blocks belong to this item while indented deeper.
    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) {
        let look = index + 1;
        while (look < lines.length && !lines[look].trim()) look++;
        if (look < lines.length && indentOf(lines[look]) > indent) {
          item.children.push("");
          index++;
          continue;
        }
        break;
      }
      if (indentOf(line) > indent) {
        item.children.push(line);
        index++;
        continue;
      }
      break;
    }
    items.push(item);

    // One blank line between two items of the same list does not end it.
    if (index < lines.length && !lines[index].trim()) {
      let look = index + 1;
      while (look < lines.length && !lines[look].trim()) look++;
      const next = look < lines.length ? LIST.exec(lines[look]) : null;
      if (next && indentOf(next[1]) === indent && /\d/.test(next[2]) === ordered) index = look;
    }
  }

  if (items.length === 0) return null;

  const reference = `list-${start}-${depth}`;
  const rendered = items.map((item, position) => {
    const task = TASK.exec(item.text);
    const content = task ? task[2] : item.text;
    const nested =
      item.children.length > 0
        ? renderBlocks(dedent(item.children, indent + 2).join("\n"), depth + 1)
        : null;
    return (
      <li key={position} className={task ? "task-item" : undefined}>
        {task && (
          <input
            type="checkbox"
            checked={task[1].toLowerCase() === "x"}
            readOnly
            disabled
            tabIndex={-1}
            aria-label={task[1].toLowerCase() === "x" ? "Done" : "To do"}
          />
        )}
        <span className="li-text">{renderInline(content)}</span>
        {nested}
      </li>
    );
  });

  return {
    node: ordered ? (
      <ol key={reference}>{rendered}</ol>
    ) : (
      <ul key={reference} className={items.some((item) => TASK.test(item.text)) ? "task-list" : undefined}>
        {rendered}
      </ul>
    ),
    end: index,
  };
}

function paragraphLines(lines: string[]): ReactNode[] {
  const nodes: ReactNode[] = [];
  lines.forEach((line, position) => {
    if (position) nodes.push(<br key={`br-${position}`} />);
    nodes.push(...renderInline(line));
  });
  return nodes;
}

function startsBlock(lines: string[], index: number): boolean {
  const line = lines[index];
  if (FENCE.test(line) || HEADING.test(line) || RULE.test(line) || QUOTE.test(line) || LIST.test(line)) return true;
  return tableAt(lines, index) !== null;
}

function renderBlocks(text: string, depth = 0): ReactNode[] {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  const add = (node: ReactNode) => blocks.push(node);
  let index = 0;

  // Deeply nested quotes or lists fall back to plain lines instead of recursing without bound.
  if (depth > 8) {
    return [<p key="deep">{paragraphLines(lines)}</p>];
  }

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index++;
      continue;
    }

    const fence = FENCE.exec(line);
    if (fence) {
      const marker = fence[1][0] === "`" ? "`" : "~";
      const size = fence[1].length;
      const language = fence[2].trim().split(/\s+/)[0] ?? "";
      const code: string[] = [];
      index++;
      while (index < lines.length) {
        const closing = new RegExp(`^\\s{0,3}${marker}{${size},}\\s*$`);
        if (closing.test(lines[index])) {
          index++;
          break;
        }
        code.push(lines[index]);
        index++;
      }
      add(<CodeBlock key={blocks.length} code={code.join("\n")} language={language} />);
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      const level = Math.min(4, heading[1].length) as 1 | 2 | 3 | 4;
      const Tag = `h${level}` as "h1" | "h2" | "h3" | "h4";
      add(<Tag key={blocks.length}>{renderInline(heading[2])}</Tag>);
      index++;
      continue;
    }

    if (RULE.test(line)) {
      add(<hr key={blocks.length} />);
      index++;
      continue;
    }

    if (QUOTE.test(line)) {
      const quoted: string[] = [];
      while (index < lines.length && QUOTE.test(lines[index])) {
        quoted.push(lines[index].replace(/^\s{0,3}>\s?/, ""));
        index++;
      }
      add(<blockquote key={blocks.length}>{renderBlocks(quoted.join("\n"), depth + 1)}</blockquote>);
      continue;
    }

    if (LIST.test(line)) {
      const list = listAt(lines, index, depth);
      if (list) {
        add(list.node);
        index = list.end;
        continue;
      }
    }

    const table = tableAt(lines, index);
    if (table) {
      add(<Fragment key={blocks.length}>{table.node}</Fragment>);
      index = table.end;
      continue;
    }

    const paragraph: string[] = [];
    while (index < lines.length) {
      if (!lines[index].trim()) break;
      if (paragraph.length > 0 && startsBlock(lines, index)) break;
      paragraph.push(lines[index]);
      index++;
    }
    add(<p key={blocks.length}>{paragraphLines(paragraph)}</p>);
  }

  return blocks;
}

export function Markdown({ text }: { text: string }) {
  return <div className="md">{renderBlocks(text)}</div>;
}
