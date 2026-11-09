/** Which view the owner works in: the voice stage with the thread beside it, or the thread alone. Kept per browser. */
export type ViewMode = "voice" | "chat";

export const VIEW_MODE_KEY = "savant.view";
export const DEFAULT_VIEW_MODE: ViewMode = "voice";

export function isViewMode(value: unknown): value is ViewMode {
  return value === "voice" || value === "chat";
}

export function loadViewMode(storage?: Pick<Storage, "getItem">): ViewMode {
  try {
    const raw = (storage ?? window.localStorage).getItem(VIEW_MODE_KEY);
    return isViewMode(raw) ? raw : DEFAULT_VIEW_MODE;
  } catch {
    return DEFAULT_VIEW_MODE;
  }
}

export function saveViewMode(mode: ViewMode, storage?: Pick<Storage, "setItem">): void {
  try {
    (storage ?? window.localStorage).setItem(VIEW_MODE_KEY, mode);
  } catch {
    // Blocked or full: the choice lasts for this page only.
  }
}
