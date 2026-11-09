import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { ActivityEntry } from "../activity";
import { notionView, outlookView, type ConnectionView } from "../connections";
import { usePresence } from "../hooks/usePresence";
import type { MotionPreference } from "../motion";
import type { Theme } from "../theme";
import { NOTION_TOOLS, OUTLOOK_TOOLS, SSH_TOOLS, toolLabel } from "../tools";
import type { NotionState } from "../useNotion";
import { OUTLOOK_ENABLED, type OutlookState } from "../useOutlook";
import type { VoiceLanguage } from "../voice";
import type { WarmState } from "../useWarmup";
import { Diagnostics } from "./Diagnostics";
import { Icon, type IconName } from "./Icon";

interface Props {
  open: boolean;
  onClose: () => void;
  notion: NotionState;
  onConnect: () => void;
  outlook: OutlookState;
  onConnectOutlook: () => void;
  activity: readonly ActivityEntry[];
  onClearActivity: () => void;
  warm: WarmState;
  theme: Theme;
  onTheme: (theme: Theme) => void;
  motion: MotionPreference;
  onMotion: (motion: MotionPreference) => void;
  language: VoiceLanguage;
  onLanguage: (language: VoiceLanguage) => void;
  speakAloud: boolean;
  onSpeakAloud: (value: boolean) => void;
}

const THEMES: { value: Theme; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select, textarea, summary, [tabindex]:not([tabindex="-1"])';

function Segmented<T extends string>({ label, options, value, onChange }: { label: string; options: { value: T; label: string }[]; value: T; onChange: (value: T) => void }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((option) => (
        <button key={option.value} type="button" className="press" aria-pressed={value === option.value} onClick={() => onChange(option.value)}>
          {option.label}
        </button>
      ))}
    </div>
  );
}

interface CardProps {
  icon: IconName;
  name: string;
  description: string;
  permissions: [string, string][];
  /** Connected / disconnected / ... for OAuth tools, "managed" or "planned" otherwise. */
  state: ConnectionView["state"] | "managed" | "planned";
  label: string;
  tone: "" | "ok" | "warn" | "err";
  action?: { label: string; run: () => void; primary: boolean };
  children?: ReactNode;
}

function ConnectionCard({ icon, name, description, permissions, state, label, tone, action, children }: CardProps) {
  return (
    <li className="conn" data-state={state}>
      <span className="conn-ic">
        <Icon name={icon} size="md" />
      </span>
      <div className="conn-body">
        <div className="conn-top">
          <b>{name}</b>
          <span className={`tag${tone ? ` ${tone}` : ""}`}>
            {state === "waiting" && <span className="spinner" aria-hidden="true" />}
            {label}
          </span>
        </div>
        <p>{description}</p>
        {permissions.length > 0 && (
          <div className="perm">
            {permissions.map(([what, how]) => (
              <span className="tag" key={what}>
                {what} · {how}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="conn-act">
        {action && (
          <button type="button" className={`btn sm press${action.primary ? " primary" : ""}`} onClick={action.run}>
            {action.label}
          </button>
        )}
      </div>
      {children && <div className="conn-wide">{children}</div>}
    </li>
  );
}

function actionFor(view: ConnectionView, run: () => void) {
  return view.action ? { label: view.action, run, primary: view.action === "Connect" } : undefined;
}

export function SettingsDrawer(props: Props) {
  const { open, onClose, notion, outlook, activity } = props;
  const { mounted, shown } = usePresence(open, 220);
  const panel = useRef<HTMLElement>(null);

  // Modal behaviour: focus moves in, the page behind is inert, Esc and Tab stay inside.
  useEffect(() => {
    if (!open || !mounted) return;
    const root = document.getElementById("root");
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const element = panel.current;
    root?.setAttribute("inert", "");

    const focusable = () => (element ? Array.from(element.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((node) => node.offsetParent !== null) : []);
    (element?.querySelector<HTMLElement>(".drawer-close") ?? focusable()[0])?.focus({ preventScroll: true });

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const list = focusable();
      if (list.length === 0) {
        event.preventDefault();
        return;
      }
      const first = list[0];
      const last = list[list.length - 1];
      const current = document.activeElement;
      if (event.shiftKey && (current === first || !element?.contains(current))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (current === last || !element?.contains(current))) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      root?.removeAttribute("inert");
      previous?.focus({ preventScroll: true });
    };
  }, [open, mounted, onClose]);

  const used = useMemo(() => {
    const names = new Set<string>();
    for (const entry of activity) if (entry.kind === "tool" && entry.tool) names.add(entry.tool);
    return Array.from(names).map((name) => ({
      name,
      label: toolLabel(name),
      write: NOTION_TOOLS.find((tool) => tool.name === name)?.access === "write",
    }));
  }, [activity]);

  if (!mounted) return null;

  const reads = NOTION_TOOLS.filter((tool) => tool.access === "read");
  const writes = NOTION_TOOLS.filter((tool) => tool.access === "write");
  const notionState = notionView(notion);
  const mailState = outlookView(outlook);

  return createPortal(
    <>
      <div
        className="settings-scrim"
        data-open={shown ? "" : undefined}
        onMouseDown={(event) => {
          if (event.target === event.currentTarget) onClose();
        }}
      />
      <aside className="settings" data-open={shown ? "" : undefined} role="dialog" aria-modal="true" aria-labelledby="settings-title" ref={panel} inert={!shown}>
        <header className="s-head">
          <h2 id="settings-title">Settings</h2>
          <button type="button" className="icon-btn press drawer-close" aria-label="Close settings" onClick={onClose}>
            <Icon name="x" size="md" />
          </button>
        </header>

        <div className="s-body">
          <section aria-labelledby="s-conn">
            <h3 id="s-conn">Tools &amp; connections</h3>
            <p className="s-lead">Savant uses these tools on your behalf. Anything that changes data asks for your approval first, whatever is connected.</p>
            <ul className="conns">
              <ConnectionCard
                icon="doc"
                name="Notion"
                description="Search and read your workspace. Anything that changes a page asks for your approval first."
                permissions={[["Read", "direct"], ["Write", "asks first"]]}
                state={notionState.state}
                label={notionState.label}
                tone={notionState.tone}
                action={actionFor(notionState, props.onConnect)}
              >
                <details className="what">
                  <summary>What it can do</summary>
                  <p className="note">Notion consent grants access to the workspace. Each write then asks for your approval. Preview: the live list needs a BFF route.</p>
                  <h4 className="tool-group">Read</h4>
                  <ul className="tool-list">
                    {reads.map((tool) => (
                      <li className="tool-item" key={tool.name}>
                        <span>{tool.label}</span>
                        <code>{tool.name}</code>
                      </li>
                    ))}
                  </ul>
                  <h4 className="tool-group">Write</h4>
                  <ul className="tool-list">
                    {writes.map((tool) => (
                      <li className="tool-item" key={tool.name}>
                        <span>{tool.label}</span>
                        <span className="tool-tag">asks for approval</span>
                      </li>
                    ))}
                  </ul>
                  <h4 className="tool-group">Used in this session</h4>
                  {used.length === 0 ? (
                    <p className="note">No tool used yet.</p>
                  ) : (
                    <ul className="tool-list">
                      {used.map((tool) => (
                        <li className="tool-item" key={tool.name}>
                          <span>{tool.label}</span>
                          {tool.write && <span className="tool-tag">asked for approval</span>}
                        </li>
                      ))}
                    </ul>
                  )}
                </details>
              </ConnectionCard>

              {OUTLOOK_ENABLED && (
                <ConnectionCard
                  icon="mail"
                  name="Outlook"
                  description="Read mail and calendar. Sending or deleting always asks first."
                  permissions={[["Read", "direct"], ["Send · delete", "asks first"]]}
                  state={mailState.state}
                  label={mailState.label}
                  tone={mailState.tone}
                  action={actionFor(mailState, props.onConnectOutlook)}
                >
                  <details className="what">
                    <summary>What it can do</summary>
                    <p className="note">Mail content is untrusted: instructions inside an email never count as your approval.</p>
                    <ul className="tool-list">
                      {OUTLOOK_TOOLS.map((tool) => (
                        <li className="tool-item" key={tool.label}>
                          <span>{tool.label}</span>
                          <span className="tool-tag">{tool.access === "approval" ? "asks for approval" : "direct"}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                </ConnectionCard>
              )}

              <ConnectionCard icon="globe" name="Web search" description="Look things up on the web. Managed by Azure: nothing to connect." permissions={[["Read", "direct"]]} state="managed" label="Managed by the agent" tone="">
                <details className="what">
                  <summary>What it can do</summary>
                  <ul className="tool-list">
                    <li className="tool-item">
                      <span>Web search</span>
                      <span className="tool-tag">direct</span>
                    </li>
                    <li className="tool-item">
                      <span>Code interpreter</span>
                      <span className="tool-tag">asks for approval</span>
                    </li>
                  </ul>
                  <p className="note">Web pages are untrusted: instructions found online never count as your approval.</p>
                </details>
              </ConnectionCard>

              <ConnectionCard
                icon="term"
                name="Linux VM (SSH)"
                description="Run commands on your VM. Destructive commands always ask first."
                permissions={[["Commands", "one at a time"], ["Destructive", "asks first"]]}
                state="managed"
                label="Managed by the agent"
                tone=""
              >
                <details className="what">
                  <summary>What it can do</summary>
                  <p className="note">The agent acts on a dedicated account of the Linux VM, with no state between two commands.</p>
                  <ul className="tool-list">
                    {SSH_TOOLS.map((tool) => (
                      <li className="tool-item" key={tool.name}>
                        <span>
                          {tool.label}
                          <span className="tool-detail">{tool.detail}</span>
                        </span>
                        <code>{tool.name}</code>
                      </li>
                    ))}
                  </ul>
                  <h4 className="tool-group">Caution rule</h4>
                  <ul className="tool-list">
                    <li className="tool-item">
                      <span>Reads and additions (new file, append)</span>
                      <span className="tool-tag">direct</span>
                    </li>
                    <li className="tool-item">
                      <span>Deletions, overwrites, bulk or system changes</span>
                      <span className="tool-tag">asks for approval</span>
                    </li>
                  </ul>
                  <p className="note">
                    A second model judges every command before it runs; when in doubt, it asks. Commands that would reveal secrets are refused. You answer in your own words, by voice or text; an approval covers a single command.
                  </p>
                </details>
              </ConnectionCard>

              <ConnectionCard icon="mail" name="Gmail" description="Search, read and send mail. Not available yet." permissions={[]} state="planned" label="Planned" tone="" />
            </ul>
          </section>

          <section aria-labelledby="s-voice">
            <h3 id="s-voice">Voice</h3>
            <div className="s-row">
              <span>
                Spoken language
                <small>Recognition and the voice that answers follow it</small>
              </span>
              <Segmented<VoiceLanguage> label="Spoken language" value={props.language} onChange={props.onLanguage} options={[{ value: "fr-FR", label: "Français" }, { value: "en-US", label: "English" }]} />
            </div>
            <div className="s-row">
              <span>
                Read answers aloud
                <small>Off: answers stay in the thread, and tool announcements stop too</small>
              </span>
              <button type="button" className="switch press" role="switch" aria-checked={props.speakAloud} aria-label="Read answers aloud" onClick={() => props.onSpeakAloud(!props.speakAloud)} />
            </div>
          </section>

          <section aria-labelledby="s-look">
            <h3 id="s-look">Appearance</h3>
            <div className="s-row">
              <span>Theme</span>
              <Segmented<Theme> label="Theme" value={props.theme} onChange={props.onTheme} options={THEMES} />
            </div>
            <div className="s-row">
              <span>
                Reduce motion
                <small>Keeps fades, drops movement</small>
              </span>
              <Segmented<MotionPreference> label="Reduce motion" value={props.motion} onChange={props.onMotion} options={[{ value: "system", label: "System" }, { value: "reduce", label: "On" }]} />
            </div>
          </section>

          <section aria-labelledby="s-diag">
            <h3 id="s-diag">Diagnostics</h3>
            <Diagnostics entries={activity} notion={notion} warm={props.warm} onClear={props.onClearActivity} />
          </section>

          <section aria-labelledby="s-acc">
            <h3 id="s-acc">Account</h3>
            <p className="s-lead">Owner · Microsoft Entra ID · single user.</p>
          </section>
        </div>
      </aside>
    </>,
    document.body,
  );
}
