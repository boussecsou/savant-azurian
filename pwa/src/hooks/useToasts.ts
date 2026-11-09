import { useCallback, useEffect, useRef, useState } from "react";

export type ToastKind = "ok" | "err" | "info";

export interface ToastInput {
  message: string;
  kind?: ToastKind;
  /** e.g. Undo. */
  action?: { label: string; run: () => void };
  /** How long it stays when nobody is pointing at it. */
  ms?: number;
  /** Called once when the toast goes away without its action being used. */
  onExpire?: () => void;
}

export interface Toast extends ToastInput {
  id: number;
  leaving: boolean;
}

export const TOAST_MS = 5200;
export const TOAST_EXTRA_MS = 2200;
export const TOAST_EXIT_MS = 130;

/** A stack of short messages. Hovering one pauses its countdown; leaving it adds a little time back. */
export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef(new Map<number, number>());
  const next = useRef(1);
  const live = useRef(new Map<number, Toast>());

  const clearTimer = (id: number) => {
    const timer = timers.current.get(id);
    if (timer !== undefined) window.clearTimeout(timer);
    timers.current.delete(id);
  };

  const remove = useCallback((id: number, expired: boolean) => {
    clearTimer(id);
    const toast = live.current.get(id);
    if (!toast) return;
    live.current.delete(id);
    setToasts((list) => list.map((t) => (t.id === id ? { ...t, leaving: true } : t)));
    window.setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), TOAST_EXIT_MS);
    if (expired) toast.onExpire?.();
  }, []);

  const arm = useCallback(
    (id: number, ms: number) => {
      clearTimer(id);
      timers.current.set(id, window.setTimeout(() => remove(id, true), ms));
    },
    [remove],
  );

  const push = useCallback(
    (input: ToastInput) => {
      const id = next.current++;
      const toast: Toast = { ...input, id, leaving: false };
      live.current.set(id, toast);
      setToasts((list) => [...list, toast].slice(-4));
      arm(id, input.ms ?? TOAST_MS);
      return id;
    },
    [arm],
  );

  const act = useCallback(
    (id: number) => {
      const toast = live.current.get(id);
      if (!toast) return;
      remove(id, false);
      toast.action?.run();
    },
    [remove],
  );

  const pause = useCallback((id: number) => clearTimer(id), []);
  const resume = useCallback((id: number) => arm(id, TOAST_EXTRA_MS), [arm]);

  // Toasts still waiting when the app goes away: let their cleanup run.
  useEffect(
    () => () => {
      for (const timer of timers.current.values()) window.clearTimeout(timer);
      timers.current.clear();
    },
    [],
  );

  return { toasts, push, act, pause, resume };
}
