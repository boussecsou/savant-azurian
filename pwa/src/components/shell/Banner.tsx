import { useRef } from "react";
import { usePresence } from "../../hooks/usePresence";
import { Icon, type IconName } from "../Icon";

export interface BannerContent {
  tone: "warn" | "err" | "info";
  icon: IconName;
  title: string;
  text: string;
  action?: { label: string; run: () => void };
}

/** Under the top bar: one message at a time, for what the owner must know about (access, network, a tool). */
export function Banner({ content }: { content: BannerContent | null }) {
  const { mounted, shown } = usePresence(content !== null, 200);
  const last = useRef<BannerContent | null>(null);
  if (content) last.current = content;
  const current = content ?? last.current;
  return (
    <div className="banner" role="status" data-open={shown ? "" : undefined} data-tone={current?.tone}>
      {mounted && current && (
        <>
          <Icon name={current.icon} />
          <p>
            <strong>{current.title}</strong> {current.text}
          </p>
          {current.action && (
            <button type="button" className="btn sm press" onClick={current.action.run}>
              {current.action.label}
            </button>
          )}
        </>
      )}
    </div>
  );
}
