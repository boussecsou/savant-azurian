import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { usePresence } from "../../hooks/usePresence";
import { Icon, type IconName } from "../Icon";

export type MenuEntry =
  | { kind: "item"; id: string; label: string; icon?: IconName; danger?: boolean; onSelect: () => void }
  | { kind: "separator" }
  | { kind: "label"; label: string };

/** Where a menu hangs: under a button, or at the pointer for a right click. */
export type MenuAnchor = { rect: { left: number; right: number; top: number; bottom: number } };

export interface MenuState {
  entries: MenuEntry[];
  anchor: MenuAnchor;
  /** Where focus returns when the menu closes by keyboard or selection. */
  returnFocus: HTMLElement | null;
}

/** State and openers for the one menu the app shows at a time. */
export function useMenu() {
  const [menu, setMenu] = useState<MenuState | null>(null);

  const openFrom = useCallback((trigger: HTMLElement, entries: MenuEntry[]) => {
    const rect = trigger.getBoundingClientRect();
    setMenu({ entries, anchor: { rect }, returnFocus: trigger });
  }, []);

  const openAt = useCallback((x: number, y: number, entries: MenuEntry[]) => {
    setMenu({ entries, anchor: { rect: { left: x, right: x, top: y, bottom: y } }, returnFocus: document.activeElement instanceof HTMLElement ? document.activeElement : null });
  }, []);

  const close = useCallback(() => setMenu(null), []);
  return { menu, openFrom, openAt, close };
}

const EXIT_MS = 110;
const GAP = 6;
const EDGE = 8;

interface Placement {
  left: number;
  top: number;
  ox: number;
  oy: number;
}

/** A menu that opens from its trigger: it scales up from that point, flips above when there is no room below. */
export function PopoverMenu({ menu, onClose }: { menu: MenuState | null; onClose: () => void }) {
  const { mounted, shown } = usePresence(menu !== null, EXIT_MS);
  // Keep the last menu on screen while it fades out.
  const last = useRef<MenuState | null>(null);
  if (menu) last.current = menu;
  const current = menu ?? last.current;
  const element = useRef<HTMLDivElement>(null);
  const [placement, setPlacement] = useState<Placement | null>(null);

  useLayoutEffect(() => {
    if (!menu || !element.current) return;
    const { rect } = menu.anchor;
    const { offsetWidth: w, offsetHeight: h } = element.current;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = rect.right - w;
    if (rect.right === rect.left) left = rect.left;
    left = Math.max(EDGE, Math.min(left, vw - w - EDGE));
    const roomBelow = vh - rect.bottom - GAP - EDGE;
    const above = roomBelow < h && rect.top - GAP - EDGE > roomBelow;
    const top = above ? Math.max(EDGE, rect.top - GAP - h) : Math.min(rect.bottom + GAP, Math.max(EDGE, vh - h - EDGE));
    const anchorX = Math.max(rect.left, Math.min(rect.right, rect.right - 14));
    setPlacement({ left, top, ox: Math.max(0, Math.min(w, anchorX - left)), oy: above ? h : 0 });
  }, [menu]);

  // Focus the first item once it is visible; close on a press outside.
  useEffect(() => {
    if (!menu || !shown) return;
    element.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus({ preventScroll: true });
    const onDown = (event: PointerEvent) => {
      if (element.current && !element.current.contains(event.target as Node)) onClose();
    };
    document.addEventListener("pointerdown", onDown, true);
    return () => document.removeEventListener("pointerdown", onDown, true);
  }, [menu, shown, onClose]);

  const finish = useCallback(
    (restore: boolean) => {
      const target = menu?.returnFocus;
      onClose();
      if (restore) target?.focus({ preventScroll: true });
    },
    [menu, onClose],
  );

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const items = Array.from(element.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []);
    const index = items.indexOf(document.activeElement as HTMLElement);
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      finish(true);
    } else if (event.key === "Tab") {
      finish(false);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Home" || event.key === "End") {
      event.preventDefault();
      if (items.length === 0) return;
      const next =
        event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : event.key === "ArrowDown" ? (index + 1) % items.length : (index - 1 + items.length) % items.length;
      items[next].focus();
    }
  };

  if (!mounted || !current) return null;
  return createPortal(
    <div
      ref={element}
      className="menu"
      role="menu"
      data-open={shown && placement ? "" : undefined}
      onKeyDown={onKeyDown}
      style={{ left: placement?.left ?? 0, top: placement?.top ?? 0, ["--ox" as string]: `${placement?.ox ?? 0}px`, ["--oy" as string]: `${placement?.oy ?? 0}px` }}
    >
      {current.entries.map((entry, index) => {
        if (entry.kind === "separator") return <hr key={`sep-${index}`} />;
        if (entry.kind === "label") return <div key={`label-${index}`} className="label">{entry.label}</div>;
        return (
          <button
            key={entry.id}
            type="button"
            role="menuitem"
            className={entry.danger ? "danger" : undefined}
            onClick={() => {
              finish(true);
              entry.onSelect();
            }}
          >
            {entry.icon && <Icon name={entry.icon} />}
            {entry.label}
          </button>
        );
      })}
    </div>,
    document.body,
  );
}
