import { useEffect, useReducer, useRef } from "react";

const reducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;

/**
 * Reveal `target` progressively. Text that arrives in bursts flows out smoothly: each frame
 * shows a tenth of the backlog (at least two characters), so a long answer catches up in
 * about a second and a slow stream stays steady. Without `animate`, or for people who ask for
 * less motion, the text is shown as it is.
 */
export function useReveal(target: string, animate: boolean): { shown: string; catchingUp: boolean } {
  const length = useRef(animate && !reducedMotion() ? 0 : target.length);
  const [, render] = useReducer((count: number) => count + 1, 0);

  useEffect(() => {
    if (!animate || reducedMotion()) {
      length.current = target.length;
      render();
      return;
    }
    if (length.current > target.length) length.current = target.length;
    let frame = 0;
    const tick = () => {
      const backlog = target.length - length.current;
      if (backlog > 0) {
        length.current += Math.min(backlog, Math.max(2, Math.ceil(backlog / 10)));
        render();
      }
      if (length.current < target.length) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, animate]);

  return { shown: target.slice(0, length.current), catchingUp: length.current < target.length };
}
