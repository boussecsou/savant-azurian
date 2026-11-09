/**
 * "Reduce motion": the owner's choice (System or On) combined with the OS preference.
 * It is applied as data-motion="reduce" on <html>, which is the single source the stylesheet reads:
 * movement goes away, fades stay.
 */
export type MotionPreference = "system" | "reduce";

export const MOTION_KEY = "sa2-motion";

export function isMotionPreference(value: unknown): value is MotionPreference {
  return value === "system" || value === "reduce";
}

export function resolveMotion(preference: MotionPreference, osReduces: boolean): "full" | "reduce" {
  return preference === "reduce" || osReduces ? "reduce" : "full";
}

export function loadMotion(storage: Pick<Storage, "getItem"> | undefined = defaultStorage()): MotionPreference {
  try {
    const raw = storage?.getItem(MOTION_KEY);
    return isMotionPreference(raw) ? raw : "system";
  } catch {
    return "system";
  }
}

export function saveMotion(preference: MotionPreference, storage: Pick<Storage, "setItem"> | undefined = defaultStorage()): void {
  try {
    storage?.setItem(MOTION_KEY, preference);
  } catch {
    // Blocked or full: the choice lasts for this page only.
  }
}

function defaultStorage(): Storage | undefined {
  try {
    return typeof window === "undefined" ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}
