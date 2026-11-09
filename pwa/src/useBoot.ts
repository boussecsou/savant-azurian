import { useEffect, useRef, useState } from "react";
import { bootPhase, nextBootChange, type BootPhase } from "./boot";

/** The phase of the start-up screen (see boot.ts), given whether the workspace sync has finished. */
export function useBoot(synced: boolean): BootPhase {
  const start = useRef<number | null>(null);
  const settledAt = useRef<number | null>(null);
  const [, render] = useState(0);
  const now = performance.now();
  if (start.current === null) start.current = now;
  if (synced && settledAt.current === null) settledAt.current = now;
  const times = { start: start.current, settledAt: settledAt.current };
  const phase = bootPhase(now, times);

  useEffect(() => {
    const next = nextBootChange(performance.now(), { start: start.current as number, settledAt: settledAt.current });
    if (next === null) return;
    const timer = window.setTimeout(() => render((n) => n + 1), Math.max(0, next - performance.now()) + 1);
    return () => window.clearTimeout(timer);
  }, [phase, synced]);

  return phase;
}
