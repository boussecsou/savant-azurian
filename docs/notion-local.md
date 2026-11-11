# Testing the Notion MCP server locally

The existing LangGraph graph receives the tools of the official Notion server through `langchain.mcp.MCPAdapter`. `ToolNode` runs these tools without changing their schemas, structured results or MCP errors. Configured writes ask for approval before each call. There is no restriction to a given page: the rights of your Notion OAuth account determine which pages are accessible.

## Prepare the connection

Install the locked dependencies:

```bash
uv sync --locked --group dev
```

From a local terminal, discover the exact names of the available tools:

```bash
uv run --locked python -m savant.tools.notion
```

This command opens the browser so you can sign in to Notion, then prints the tool catalogue. It neither reads nor changes a page and does not contact Azure.

If the automatic opening prints `gio: Operation not supported`, open the authorization URL printed in the terminal by hand, keeping the command running. The `localhost` callback must be reachable from that browser.

The OAuth registration explicitly asks for the public client mode `none` with PKCE, which Notion accepts. This avoids the MCP SDK's defect of duplicating `client_id` in requests that use HTTP Basic ([SDK issue](https://github.com/modelcontextprotocol/python-sdk/issues/3138)).

In your local `.env`, keep the existing Azure OpenAI variables and add:

```dotenv
NOTION_MCP_ENABLED=true
NOTION_MCP_URL=https://mcp.notion.com/mcp
NOTION_READ_TOOL_NAMES=EXACT_NAMES_OF_THE_READ_TOOLS_SEPARATED_BY_COMMAS
NOTION_WRITE_TOOL_NAMES=EXACT_NAMES_OF_THE_WRITE_TOOLS_SEPARATED_BY_COMMAS
```

Put the search and read tools in the first list, and those that change Notion in the second. A name cannot appear in both. Leaving the second list empty lets you test reading only. Tools missing from the lists are not exposed to the model; an unknown name makes startup fail with the names the server offers.

## Start, then read a page

```bash
uv run --locked python main.py
```

Startup asks for the Notion OAuth connection before opening the server. The OAuth tokens stay in memory: you must reconnect after every restart, including after the catalogue discovery command. The model uses the existing Azure authentication; this integration runs no Azure sign-in or deployment command.

In a second terminal:

```bash
curl --fail-with-body http://localhost:8088/responses \
  -H 'Content-Type: application/json' \
  -d '{"input":"Read this Notion page and summarize it: https://www.notion.so/<your-page-url>","stream":false}'
```

## Test a write with approval

Ask for a small change on a page of your choice, for example adding a paragraph "Local test". The agent returns an `mcp_approval_request` output. Its `arguments` field holds the tool name, its exact arguments and the call identifier, in the LangGraph interruption envelope. Check these arguments before answering.

Resume with the `id` of that output and the `id` of the initial response:

```bash
curl --fail-with-body http://localhost:8088/responses \
  -H 'Content-Type: application/json' \
  -d '{"previous_response_id":"RESPONSE_ID","input":[{"type":"mcp_approval_response","approval_request_id":"REQUEST_ID","approve":true}],"stream":false}'
```

With `approve:false`, the server reports `interrupt_rejected` and does not run the write. Interruptions and conversations stay in memory for this local test and disappear when the process restarts.

This is the local test of the generic approval path. In production, Notion writes go through the conversational consent described in [notion-semantic-approval.md](notion-semantic-approval.md).

## Automatic validation

```bash
uv run --locked pytest
```

The tests use simulated models and transports: they cover the wiring, the tool lists, MCP results and errors, and the approval or refusal of writes. The OAuth connection and the real calls to Notion are to be checked with the local test above. The integration is disabled by default in `.env.example`. No Azure configuration or deployment change is needed for this step.
