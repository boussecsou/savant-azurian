import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { filterCommands, type Command } from "../../palette";

interface Props {
  open: boolean;
  onClose: () => void;
  commands: readonly Command[];
}

/** Ctrl/⌘+K. Opens and navigates instantly: keyboard actions are done many times a day, so they do not animate. */
export function CommandPalette({ open, onClose, commands }: Props) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const results = useMemo(() => filterCommands(commands, query), [commands, query]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setIndex(0);
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.getElementById("root")?.setAttribute("inert", "");
    input.current?.focus();
    return () => {
      document.getElementById("root")?.removeAttribute("inert");
      previous?.focus?.({ preventScroll: true });
    };
  }, [open]);

  useEffect(() => setIndex(0), [query]);
  useEffect(() => {
    list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [index]);

  if (!open) return null;

  const run = (command: Command | undefined) => {
    if (!command) return;
    onClose();
    // After the palette has gone: the command may move focus.
    window.setTimeout(command.run, 0);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      if (results.length) setIndex((i) => (i + 1) % results.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (results.length) setIndex((i) => (i - 1 + results.length) % results.length);
    } else if (event.key === "Enter" && !event.nativeEvent.isComposing) {
      event.preventDefault();
      run(results[index]);
    }
  };

  return createPortal(
    <div
      className="palette-scrim"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="palette" role="dialog" aria-modal="true" aria-label="Command palette">
        <input
          ref={input}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Search sessions, projects and actions"
          aria-label="Command palette"
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-list"
          aria-activedescendant={results[index] ? `palette-${results[index].id}` : undefined}
          autoComplete="off"
        />
        <ul id="palette-list" role="listbox" ref={list}>
          {results.length === 0 ? (
            <li className="none">Nothing matches “{query}”.</li>
          ) : (
            results.map((command, i) => (
              <li key={command.id}>
                <button
                  type="button"
                  id={`palette-${command.id}`}
                  role="option"
                  aria-selected={i === index}
                  tabIndex={-1}
                  onMouseMove={() => setIndex(i)}
                  onClick={() => run(command)}
                >
                  {command.title}
                  <span className="kind">{command.kind}</span>
                </button>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>,
    document.body,
  );
}
