import { useEffect, useState } from "react";

/**
 * Keeps something mounted while it plays its exit transition.
 * `mounted` is true from the moment `open` turns true until `exitMs` after it turns false;
 * `shown` flips one frame after mounting, so a CSS transition has a start state to leave from.
 */
export function usePresence(open: boolean, exitMs: number): { mounted: boolean; shown: boolean } {
  const [mounted, setMounted] = useState(open);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (open) {
      setMounted(true);
      const frame = requestAnimationFrame(() => setShown(true));
      return () => cancelAnimationFrame(frame);
    }
    setShown(false);
    const timer = window.setTimeout(() => setMounted(false), exitMs);
    return () => window.clearTimeout(timer);
  }, [open, exitMs]);

  return { mounted: open || mounted, shown: open && shown };
}
