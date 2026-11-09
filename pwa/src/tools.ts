/** Plain-language names for the tool calls the agent reports. */

const LABELS: Record<string, string> = {
  "notion-search": "Searching Notion",
  "notion-fetch": "Reading a page",
  "notion-query-data-sources": "Reading a database",
  "notion-query-multiple-data-sources": "Reading several databases",
  "notion-query-meeting-notes": "Reading meeting notes",
  "notion-get-comments": "Reading comments",
  "notion-get-users": "Looking up users",
  "notion-get-teams": "Reading teams",
  "notion-get-self": "Reading the profile",
  "notion-get-tool-access": "Checking access",
  "notion-create-pages": "Creating a page",
  "notion-update-page": "Updating a page",
  "notion-create-comment": "Adding a comment",
  "notion-create-database": "Creating a database",
  "notion-move-pages": "Moving pages",
  "notion-duplicate-page": "Duplicating a page",
  "notion-delete-pages": "Deleting pages",
  connect_notion: "Connecting to Notion",
  read_ssh_skill: "Reading the SSH rules",
  ssh_exec: "Running a command on the VM",
  search_documents: "Searching the project's sources",
  tool_search: "Looking for a tool",
  call_tool: "Running a tool",
  oauth_consent_required: "Outlook sign-in required",
};

/** The Outlook connector's operations, as the toolbox names them after "outlook_". */
const OUTLOOK_OPERATIONS: Record<string, string> = {
  GetEmails: "Reading emails",
  GetEmailsV2: "Reading emails",
  GetEmail: "Reading an email",
  GetAttachment: "Reading an attachment",
  CalendarGetTable: "Reading calendars",
  ContactGetTable: "Reading contact folders",
  MarkAsRead: "Marking an email as read",
  Flag: "Flagging an email",
  Move: "Moving an email",
  SendEmail: "Sending an email",
  SendEmailV2: "Sending an email",
  ReplyToV3: "Replying to an email",
  DeleteEmail: "Deleting an email",
};

const FALLBACK = "Agent action";

/** Every known Notion tool either reads the workspace or changes it. */
export type ToolAccess = "read" | "write";

export interface NotionTool {
  name: string;
  label: string;
  access: ToolAccess;
}

const WRITE_TOOLS = new Set([
  "notion-create-pages",
  "notion-update-page",
  "notion-create-comment",
  "notion-create-database",
  "notion-move-pages",
  "notion-duplicate-page",
  "notion-delete-pages",
]);

/**
 * Static preview of the Notion tool catalog. The BFF does not expose the live list
 * yet, so the settings drawer reads this and says so.
 */
export const NOTION_TOOLS: readonly NotionTool[] = Object.entries(LABELS)
  .filter(([name]) => name.startsWith("notion-"))
  .map(([name, label]) => ({ name, label, access: WRITE_TOOLS.has(name) ? "write" : "read" }));

/** The VM tools. SSH steps get a "VM" badge so they are never mistaken for Notion work. */
export interface SshTool {
  name: string;
  label: string;
  detail: string;
}

export const SSH_TOOLS: readonly SshTool[] = [
  {
    name: "read_ssh_skill",
    label: LABELS.read_ssh_skill,
    detail: "The agent rereads its rules before each SSH conversation.",
  },
  {
    name: "ssh_exec",
    label: LABELS.ssh_exec,
    detail: "One command at a time, on a dedicated VM account.",
  },
];

export function isSshTool(name: string | undefined): boolean {
  return SSH_TOOLS.some((tool) => tool.name === name);
}

/** Outlook: what runs directly and what always asks first. */
export type OutlookAccess = "direct" | "approval";

export interface OutlookTool {
  label: string;
  access: OutlookAccess;
}

export const OUTLOOK_TOOLS: readonly OutlookTool[] = [
  { label: "Read emails and attachments", access: "direct" },
  { label: "Mark as read, flag, move", access: "direct" },
  { label: "Send or reply to an email", access: "approval" },
  { label: "Delete an email", access: "approval" },
];

const OUTLOOK_PATTERN = /(?:^|___)outlook_([A-Za-z0-9]+)$/;

export function outlookOperation(name: string | undefined): string | undefined {
  return name?.match(OUTLOOK_PATTERN)?.[1];
}

export function isOutlookTool(name: string | undefined): boolean {
  return outlookOperation(name) !== undefined;
}

export function toolLabel(name: string | undefined): string {
  if (!name) return FALLBACK;
  const known = LABELS[name];
  if (known) return known;
  const operation = outlookOperation(name);
  if (operation) return OUTLOOK_OPERATIONS[operation] ?? "Outlook action";
  if (/^web_search(_|$)/.test(name)) return "Searching the web";
  if (/^code_interpreter(_|$)/.test(name)) return "Running code";
  const words = name.replace(/^notion[-_]/, "").replace(/[-_]+/g, " ").trim();
  if (!words) return FALLBACK;
  const text = words.charAt(0).toUpperCase() + words.slice(1);
  return name.startsWith("notion") ? `Notion · ${text.toLowerCase()}` : text;
}
