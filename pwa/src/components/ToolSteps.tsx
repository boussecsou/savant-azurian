import { formatDuration } from "../activity";
import type { ToolStep } from "../chat";
import { isOutlookTool, isSshTool, toolLabel } from "../tools";
import { OutlookMark } from "./BrandIcons";
import { Check, Terminal } from "./Icons";

/** What the agent is doing right now, shown above its answer. */
export function ToolSteps({ tools }: { tools: ToolStep[] }) {
  return (
    <ul className="steps" aria-label="Agent actions">
      {tools.map((tool) => (
        <li key={tool.id} className="step" data-status={tool.status}>
          <span className="step-mark" aria-hidden="true">
            {tool.status === "running" ? <span className="spinner" /> : <Check />}
          </span>
          <span className="step-label">{toolLabel(tool.name)}</span>
          {isOutlookTool(tool.name) && (
            <span className="step-badge" title="Runs on your Outlook mailbox">
              <OutlookMark />
              Outlook
            </span>
          )}
          {isSshTool(tool.name) && (
            <span className="step-badge" title="Runs on the Linux VM">
              <Terminal />
              VM
            </span>
          )}
          {tool.ms !== undefined && <span className="step-ms">{formatDuration(tool.ms)}</span>}
        </li>
      ))}
    </ul>
  );
}
