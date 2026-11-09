import type { BootPhase } from "../../boot";

/**
 * The start-up screen: the logo breathes over the app while the workspace is read back from the server.
 * It covers the interface (hidden until the splash is gone, so nothing behind it can be reached) and leaves with a short fade.
 */
export function Splash({ phase }: { phase: BootPhase }) {
  if (phase !== "splash" && phase !== "leaving") return null;
  return (
    <div className="splash" data-leaving={phase === "leaving" ? "" : undefined} role="status" aria-live="polite" aria-label="Savant is starting">
      <div className="splash-mark">
        <span className="splash-ring" aria-hidden="true" />
        <img src="/icons/icon-192.png" alt="" width="72" height="72" />
      </div>
      <p className="splash-text">Updating your workspace…</p>
    </div>
  );
}
