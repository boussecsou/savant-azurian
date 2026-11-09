import { useCallback, useEffect, useState } from "react";
import { loadMotion, resolveMotion, saveMotion, type MotionPreference } from "../motion";
import { useMediaQuery } from "./useMediaQuery";

export function useMotion(): { preference: MotionPreference; setPreference: (value: MotionPreference) => void; reduced: boolean } {
  const [preference, setState] = useState<MotionPreference>(() => loadMotion());
  const osReduces = useMediaQuery("(prefers-reduced-motion: reduce)");
  const reduced = resolveMotion(preference, osReduces) === "reduce";

  useEffect(() => {
    document.documentElement.dataset.motion = reduced ? "reduce" : "full";
  }, [reduced]);

  const setPreference = useCallback((value: MotionPreference) => {
    saveMotion(value);
    setState(value);
  }, []);

  return { preference, setPreference, reduced };
}
