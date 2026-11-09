/**
 * Theme preference: system, light or dark. Stored in localStorage, applied through
 * a data-theme attribute so it wins over the prefers-color-scheme default.
 *
 * Storage can be missing or blocked (private windows, cleared site data): both
 * reading and writing degrade to "system" instead of failing.
 */

export type Theme = "system" | "light" | "dark";

export const THEME_KEY = "sa2-theme";

export const THEME_COLORS: Record<"light" | "dark", string> = {
  light: "#f6f6f9",
  dark: "#08080b",
};

export function isTheme(value: unknown): value is Theme {
  return value === "system" || value === "light" || value === "dark";
}

export function defaultStorage(): Pick<Storage, "getItem" | "setItem"> | undefined {
  try {
    return typeof window === "undefined" ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

export function loadTheme(
  storage: Pick<Storage, "getItem"> | undefined = defaultStorage(),
): Theme {
  try {
    const raw = storage?.getItem(THEME_KEY);
    return isTheme(raw) ? raw : "system";
  } catch {
    return "system";
  }
}

export function saveTheme(
  theme: Theme,
  storage: Pick<Storage, "setItem"> | undefined = defaultStorage(),
): void {
  try {
    storage?.setItem(THEME_KEY, theme);
  } catch {
    // Quota exceeded or blocked: the choice simply is not remembered.
  }
}

export function resolveTheme(theme: Theme, prefersDark: boolean): "light" | "dark" {
  return theme === "system" ? (prefersDark ? "dark" : "light") : theme;
}

export function applyTheme(
  theme: Theme,
  doc: Document | null = typeof document === "undefined" ? null : document,
  prefersDark?: boolean,
): void {
  if (!doc) return;
  const systemDark =
    prefersDark ??
    (typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
      : false);
  const root = doc.documentElement;
  // "system" leaves the attribute off so light-dark() keeps following the OS.
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
  doc
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", THEME_COLORS[resolveTheme(theme, systemDark)]);
}
