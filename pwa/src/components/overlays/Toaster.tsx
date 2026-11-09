import { useEffect, useState } from "react";
import type { Toast } from "../../hooks/useToasts";
import { Icon } from "../Icon";

interface Props {
  toasts: readonly Toast[];
  onAction: (id: number) => void;
  onPause: (id: number) => void;
  onResume: (id: number) => void;
}

function ToastItem({ toast, onAction, onPause, onResume }: { toast: Toast } & Omit<Props, "toasts">) {
  // Starts below and faded, then settles: a transition, so a burst of toasts stays interruptible.
  const [entered, setEntered] = useState(false);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setEntered(true));
    return () => cancelAnimationFrame(frame);
  }, []);
  const state = toast.leaving ? "out" : entered ? undefined : "in";
  return (
    <div
      className="toast"
      data-kind={toast.kind ?? "info"}
      data-state={state}
      onPointerEnter={() => onPause(toast.id)}
      onPointerLeave={() => onResume(toast.id)}
    >
      <span className="t-ic">
        <Icon name={toast.kind === "ok" ? "check" : toast.kind === "err" ? "alert" : "check"} />
      </span>
      <span className="t-msg">{toast.message}</span>
      {toast.action && (
        <button type="button" className="text-btn" onClick={() => onAction(toast.id)}>
          {toast.action.label}
        </button>
      )}
    </div>
  );
}

/** Short messages at the bottom, centred. Announced politely by screen readers. */
export function Toaster({ toasts, onAction, onPause, onResume }: Props) {
  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onAction={onAction} onPause={onPause} onResume={onResume} />
      ))}
    </div>
  );
}
