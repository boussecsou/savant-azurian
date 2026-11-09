import { useCallback, useEffect, useState } from "react";
import { applyTheme, loadTheme, saveTheme, type Theme } from "./theme";

export function useTheme(): { theme: Theme; setTheme: (theme: Theme) => void } {
  const [theme, setThemeState] = useState<Theme>(() => loadTheme());

  const setTheme = useCallback((next: Theme) => {
    saveTheme(next);
    setThemeState(next);
  }, []);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // While following the system, keep following it when the OS switches.
  useEffect(() => {
    if (theme !== "system") return;
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    query.addEventListener?.("change", onChange);
    return () => query.removeEventListener?.("change", onChange);
  }, [theme]);

  return { theme, setTheme };
}
