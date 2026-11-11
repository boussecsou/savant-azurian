# The Foundry Toolbox

The runtime consumes a toolbox through its consumer endpoint. `azure.yaml` sets that stable URL in `TOOLBOX_ENDPOINT`, which follows the published default version (`default_version`). The deployed toolbox is a web one: web search and the code interpreter. The existing Azure OpenAI model stays in use; the `model-router` example is not an obligation to connect a toolbox.

## Creating the toolbox

The `sa2-web` toolbox (name set by the `toolboxName` parameter of the Bicep template, `TOOLBOX_ENDPOINT` already points at it) is created in the Foundry data plane, not in Bicep:

1. In the Foundry portal, open the project, create a toolbox named `sa2-web` and add the **web search** and **code interpreter** tools. Do not add a source that needs a user connection you have not consented to.
2. Publish the version as the **default version**: the consumer endpoint serves only the default version.
3. Or use the CLI. `azd ai toolbox` has `create`, `publish`, `list`, `show` and `delete` subcommands; run `azd ai toolbox create --help` for the exact flags of your `azd` extension version. (They were not exercised while writing this page.)

A toolbox that includes an Outlook source was tried and set aside: that source made `tools/list` fail for the backend's caller and took the whole toolbox down. See [outlook-tool.md](outlook-tool.md). To run without a toolbox: `azd env set TOOLBOX_ENDPOINT ""`.

## Local use

To test locally, add to `.env`:

```dotenv
TOOLBOX_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>/toolboxes/<toolbox-name>/mcp?api-version=v1
NOTION_MCP_ENABLED=false
```

The project endpoint is extracted from this URL for the Foundry checkpoint. Toolbox mode exposes every tool discovered, plus `echo`, without needing the Notion lists. The two modes are exclusive. Discovery happens in the graph's nodes, under the user context of the request, with no network call at startup and no cache shared between users.

Tools that the toolbox marks `require_approval=always` go through our LangGraph interruption before execution. Any names in `NOTION_WRITE_TOOL_NAMES` stay protected too. This mode does not infer writes from the name: configure approvals in the toolbox. OAuth consent stays distinct, and its instructions are shown to the user when needed. Each call is also judged by name in `tools/toolbox_policy.py`: web search and direct reads run, while the code interpreter, send and delete tools and any unknown tool go through semantic consent ([ADR-0017](adr/0017-two-layer-authorization-for-notion-writes.md)).

## Installed SDK compatibility

The installed `langchain-azure-ai` has no `toolbox_version` parameter. `EndpointToolbox` overrides the `toolbox_endpoint` property to use the configured URL, consumer or versioned, including for approval discovery.

Its historical transport uses `langchain-mcp-adapters`, which imports `RequestContext`, removed in MCP 2. The existing direct backend uses `langchain[mcp]`, which requires MCP 2: pinning MCP 1 would break that backend. Our adapter therefore uses `fastmcp.Client` and `langchain.mcp.MCPAdapter`, like the direct backend, keeping the SDK's authentication, token renewal, Foundry context headers and consent handling. The SDK auth is adapted to the `httpx2.Auth` type used by FastMCP 4.

References: [official Toolbox integration](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/toolbox), [MCP 2 incompatibility](https://github.com/langchain-ai/langchain-mcp-adapters/issues/589), [new LangChain adapter](https://github.com/langchain-ai/langchain/issues/40072).

Changing the manifest does not update the agent that is already deployed. Publish a new version to use this configuration in the playground. Local discovery alone does not prove consent or the user's access through the Hosted Agent.

## Deployment and personal consent

CD tests the runtime and the real model with a dedicated request that uses no tools. It asks for no consent for the pipeline's identity. The user finishes OAuth manually in a normal playground conversation. A green CD is not an operational validation of Notion. See [cd-workflow.md](cd-workflow.md) for the exact check and its limits.

## Changing the toolbox without redeploying the agent

Changing the tools creates a new immutable version. Publishing it as the default version makes it available through the consumer endpoint. Creating or saving a version without promoting it does not change the tools served to the agent. The graph rediscovers the tools and their approvals in its nodes; it keeps no list frozen between requests.

After the initial deployment of this endpoint change, later publications need no code change and no redeployment of Savant. Avoid publishing in the middle of an operation with tools: a different version can be discovered between the decision and the execution. Test new configurations in a new conversation. A new tool or a new connection can need a personal consent.

A `/versions/<n>/mcp` URL stays accepted for testing a precise version, but does not follow later publications.
