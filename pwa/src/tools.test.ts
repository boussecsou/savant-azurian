import { describe, expect, it } from "vitest";
import { NOTION_TOOLS, OUTLOOK_TOOLS, SSH_TOOLS, isOutlookTool, isSshTool, toolLabel } from "./tools";

describe("toolLabel", () => {
  it("names the Notion tools in French", () => {
    expect(toolLabel("notion-search")).toBe("Searching Notion");
    expect(toolLabel("connect_notion")).toBe("Connecting to Notion");
  });

  it("falls back to a readable name for tools it does not know", () => {
    expect(toolLabel("notion-list-favorite-pages")).toBe("Notion · list favorite pages");
    expect(toolLabel("web_lookup")).toBe("Web lookup");
  });

  it("never returns an empty label", () => {
    expect(toolLabel(undefined)).toBe("Agent action");
    expect(toolLabel("")).toBe("Agent action");
    expect(toolLabel("---")).toBe("Agent action");
  });
});

describe("NOTION_TOOLS", () => {
  it("groups the known Notion tools into reads and writes", () => {
    const read = NOTION_TOOLS.filter((tool) => tool.access === "read").map((tool) => tool.name);
    const write = NOTION_TOOLS.filter((tool) => tool.access === "write").map((tool) => tool.name);
    expect(read).toContain("notion-search");
    expect(read).toContain("notion-fetch");
    expect(write).toContain("notion-update-page");
    expect(write).toContain("notion-delete-pages");
    expect(read).not.toContain("notion-update-page");
  });

  it("leaves the OAuth helper out of the workspace catalog", () => {
    expect(NOTION_TOOLS.map((tool) => tool.name)).not.toContain("connect_notion");
  });
});

describe("SSH tools", () => {
  it("names the VM tools in French", () => {
    expect(toolLabel("ssh_exec")).toBe("Running a command on the VM");
    expect(toolLabel("read_ssh_skill")).toBe("Reading the SSH rules");
  });

  it("recognises exactly the SSH tools, never Notion ones", () => {
    expect(SSH_TOOLS.map((tool) => tool.name)).toEqual(["read_ssh_skill", "ssh_exec"]);
    expect(isSshTool("ssh_exec")).toBe(true);
    expect(isSshTool("notion-search")).toBe(false);
    expect(isSshTool(undefined)).toBe(false);
  });

  it("keeps the VM tools out of the Notion catalog", () => {
    expect(NOTION_TOOLS.map((tool) => tool.name)).not.toContain("ssh_exec");
  });
});

describe("Outlook and toolbox tools", () => {
  it("labels the connector operations behind the toolbox prefix", () => {
    expect(toolLabel("outlook-sa2___outlook_GetEmails")).toBe("Reading emails");
    expect(toolLabel("outlook-sa2___outlook_SendEmailV2")).toBe("Sending an email");
    expect(toolLabel("outlook-sa2___outlook_DeleteEmail")).toBe("Deleting an email");
    expect(toolLabel("outlook-sa2___outlook_BrandNewOperation")).toBe("Outlook action");
  });

  it("labels the toolbox helpers and built-ins", () => {
    expect(toolLabel("tool_search")).toBe("Looking for a tool");
    expect(toolLabel("call_tool")).toBe("Running a tool");
    expect(toolLabel("web_search_m9bcyr")).toBe("Searching the web");
    expect(toolLabel("code_interpreter_spmx9p")).toBe("Running code");
    expect(toolLabel("oauth_consent_required")).toBe("Outlook sign-in required");
  });

  it("recognises Outlook tools only", () => {
    expect(isOutlookTool("outlook-sa2___outlook_Flag")).toBe(true);
    expect(isOutlookTool("notion-search")).toBe(false);
    expect(isOutlookTool("call_tool")).toBe(false);
    expect(isOutlookTool(undefined)).toBe(false);
  });

  it("says which Outlook actions always ask first", () => {
    const asking = OUTLOOK_TOOLS.filter((tool) => tool.access === "approval").map((tool) => tool.label);
    expect(asking).toEqual(["Send or reply to an email", "Delete an email"]);
  });
});
