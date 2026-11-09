import { useCallback, useEffect, useRef, useState } from "react";
import { getNotionStatus, NOTION_START_URL } from "./api";

/** unknown: first check pending · unavailable: signed out or BFF unreachable. */
export type NotionState = "unknown" | "disconnected" | "waiting" | "connected" | "unavailable";

const POLL_MS = 2000;
const GIVE_UP_MS = 3 * 60 * 1000;

export function useNotion() {
  const [state, setState] = useState<NotionState>("unknown");
  const [justConnected, setJustConnected] = useState(false);
  const current = useRef<NotionState>("unknown");
  const waitingSince = useRef<number | null>(null);

  const update = useCallback((next: NotionState) => {
    current.current = next;
    setState(next);
  }, []);

  const check = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const connected = await getNotionStatus(signal);
        if (connected) {
          if (current.current === "waiting") setJustConnected(true);
          waitingSince.current = null;
          update("connected");
        } else if (current.current !== "waiting") {
          update("disconnected");
        }
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        // A blip while the consent tab is open must not cancel the wait.
        if (current.current !== "waiting") update("unavailable");
      }
    },
    [update],
  );

  useEffect(() => {
    const controller = new AbortController();
    void check(controller.signal);
    return () => controller.abort();
  }, [check]);

  // While the consent tab is open, poll until the grant appears or we give up.
  useEffect(() => {
    if (state !== "waiting") return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      if (waitingSince.current !== null && Date.now() - waitingSince.current > GIVE_UP_MS) {
        waitingSince.current = null;
        update("disconnected");
        return;
      }
      void check();
    }, POLL_MS);
    const onVisible = () => document.visibilityState === "visible" && void check();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [state, check, update]);

  const connect = useCallback(() => {
    window.open(NOTION_START_URL, "_blank", "noopener");
    waitingSince.current = Date.now();
    setJustConnected(false);
    update("waiting");
  }, [update]);

  const acknowledge = useCallback(() => setJustConnected(false), []);

  return { state, justConnected, connect, acknowledge };
}
