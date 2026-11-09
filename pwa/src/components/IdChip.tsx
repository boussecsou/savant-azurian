import { useEffect, useRef, useState } from "react";
import { copyText } from "../clipboard";
import { Icon } from "./Icon";

/**
 * An identifier as a small button: one click copies it. The copy stays local: nothing is logged or
 * sent anywhere, since identifiers are never to be journaled.
 */
export function IdChip({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const copy = async () => {
    if (!(await copyText(id))) return;
    setCopied(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 1200);
  };

  return (
    <button
      type="button"
      className="idchip"
      data-copied={copied ? "" : undefined}
      title={copied ? "ID copied" : "Copy this ID"}
      aria-label={copied ? "ID copied" : `Copy ID ${id}`}
      onClick={() => void copy()}
    >
      {id}
      <Icon name={copied ? "check" : "copy"} />
    </button>
  );
}
