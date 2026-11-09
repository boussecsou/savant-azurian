import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, WarmupUnsupported, warmUp, type ApiErrorKind } from "./api";

/** The agent goes cold after a while: wake it again if the last wake-up is older than this. */
export const WARM_TTL_MS = 4 * 60 * 1000;
const KEY = "sa2-warm-at";

export type WarmStatus = "idle" | "warming" | "ready" | "failed" | "unsupported";
export interface WarmState {
  status: WarmStatus;
  ms?: number;
}
export interface WarmResult {
  ok: boolean;
  ms: number;
  kind?: ApiErrorKind;
  /** The BFF has no warm-up route yet: not a failure, just not available. */
  unsupported?: boolean;
}

function stamp(value?: number): number {
  try {
    if (value === undefined) return Number(window.sessionStorage.getItem(KEY)) || 0;
    window.sessionStorage.setItem(KEY, String(value));
  } catch {
    // Storage blocked: the page then wakes the agent once per load.
  }
  return value ?? 0;
}

export function isDue(last: number, now: number, ttl: number = WARM_TTL_MS): boolean {
  return now - last >= ttl;
}

/** A warm conversation: Foundry has already started its session. */
export interface SpareConversation {
  id: string;
  at: number;
}

/** Hand out the spare once, only while it is likely still warm. */
export function takeSpare(spare: SpareConversation | null, now: number, ttl: number = WARM_TTL_MS): string | undefined {
  return spare && now - spare.at < ttl ? spare.id : undefined;
}

/**
 * Wake the agent before the first message, so that message does not pay the cold start.
 * Foundry starts a new session for every new conversation, so the warm-up conversation itself is
 * kept as a spare: `take()` hands it to the next new conversation, then a new spare is prepared.
 * Runs when the page is ready and again when the tab comes back after a long pause.
 */
/** Longest wait for a warm-up already in flight before a first message goes out on its own. */
export const WARM_WAIT_MS = 25_000;

export function useWarmup(enabled: boolean, onResult: (result: WarmResult) => void): WarmState & { take: () => Promise<string | undefined> } {
  const [state, setState] = useState<WarmState>({ status: "idle" });
  const inFlight = useRef(false);
  const report = useRef(onResult);
  report.current = onResult;
  const spare = useRef<SpareConversation | null>(null);
  const runRef = useRef<((force?: boolean) => Promise<void>) | null>(null);
  const running = useRef<Promise<void> | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();

    const run = async (force = false) => {
      if (inFlight.current || (!force && !isDue(stamp(), Date.now()))) return;
      inFlight.current = true;
      stamp(Date.now());
      setState({ status: "warming" });
      const started = performance.now();
      try {
        const { ready, conversationId } = await warmUp(controller.signal);
        const ms = Math.round(performance.now() - started);
        if (!ready) throw new ApiError("upstream");
        spare.current = conversationId ? { id: conversationId, at: Date.now() } : null;
        setState({ status: "ready", ms });
        report.current({ ok: true, ms });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (error instanceof WarmupUnsupported) {
          setState({ status: "unsupported" });
          report.current({ ok: false, ms: 0, unsupported: true });
          return;
        }
        stamp(0);
        setState({ status: "failed" });
        report.current({ ok: false, ms: Math.round(performance.now() - started), kind: error instanceof ApiError ? error.kind : "unknown" });
      } finally {
        inFlight.current = false;
      }
    };

    const tracked = (force = false) => {
      const promise = run(force);
      running.current = promise;
      return promise;
    };
    runRef.current = tracked;
    void tracked();
    const onVisible = () => document.visibilityState === "visible" && void tracked();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      runRef.current = null;
      controller.abort();
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [enabled]);

  const take = useCallback(async () => {
    // A first message sent while the warm-up runs waits for it: that session is already starting,
    // a new conversation would start another one from scratch.
    if (inFlight.current && running.current) {
      await Promise.race([running.current, new Promise((resolve) => setTimeout(resolve, WARM_WAIT_MS))]);
    }
    const id = takeSpare(spare.current, Date.now());
    spare.current = null;
    // Prepare the next spare in the background, for the next new conversation.
    void runRef.current?.(true);
    return id;
  }, []);

  return { ...state, take };
}
