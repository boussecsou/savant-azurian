# Notion through Foundry: the earlier investigation

> **Superseded.** The direct path with an OAuth link in the chat is implemented and documented in [notion-chat-oauth.md](notion-chat-oauth.md) ([ADR-0009](adr/0009-bff-owns-user-facing-oauth.md)). It bypasses the Foundry custom MCP connection. This page keeps the investigation of the Foundry route and the `foundry` backend that came out of it, which is still in the code (`NOTION_BACKEND=foundry`).

State on 2 October 2026: **cloud backend written; real OAuth compatibility not validated.** The direct local test remains available in [notion-local.md](notion-local.md). The presence of OAuth features in both products is not proof of compatibility. No Azure connection or toolbox was created during this investigation. The runtime has a Foundry backend, disabled in `azure.yaml`. CD and its smoke test stay independent of Notion.

## Verified parameters

The [public Notion metadata](https://mcp.notion.com/.well-known/oauth-authorization-server) announces:

| Parameter | Value |
| --- | --- |
| MCP server | `https://mcp.notion.com/mcp` |
| Authorization | `https://mcp.notion.com/authorize` |
| Token and renewal | `https://mcp.notion.com/token` |
| Dynamic registration | `https://mcp.notion.com/register` |
| Announced scope | `default` |
| PKCE | `S256` available |
| Grants | `authorization_code`, `refresh_token` available |
| Client authentication | `none`, `client_secret_basic`, `client_secret_post` |

Do not add `offline_access`: Notion does not announce it. The [Notion client guide](https://developers.notion.com/guides/mcp/build-mcp-client) describes dynamic registration. How to register Foundry's real HTTPS callback and the matching client remained to be verified; do not automatically use the credentials of a Notion REST integration.

[Foundry OAuth](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/mcp-authentication) documents managed or custom OAuth, a callback provided after configuration and a consent link per user. The documentation consulted does not confirm a Notion entry in the project catalogue, nor the compatibility of dynamic registration with this custom flow.

[Toolbox for a Hosted Agent](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/use-toolbox-hosted-agent) confirms `AzureAIProjectToolbox` for LangGraph. Tools must be loaded with the request context. Consent and its resumption in the current LangGraph host remained to be proven in the playground.

## The Azure step that needed authorization

An already authenticated Azure session was verified outside the sandbox, without a new sign-in. A real inspection of the project showed only an Application Insights connection and a preview Foundry MCP server, plus a lab toolbox. No Notion connection and no dedicated Notion toolbox existed at the time.

`az login` would open an interactive authentication and record a session in the directory; that command waits for an explicit request, following the learning framework of this repository ([AGENTS.md](../AGENTS.md)).

After that authorization, the plan was to inspect the existing project's catalogue without creating resources. If Notion offered managed OAuth, prepare that connection; otherwise prepare the custom OAuth parameters and verify the callback registration and PKCE. Present the concrete configuration before creating any connection or toolbox.

The authorized creation would cover only the Notion connection and a dedicated toolbox, in the existing project. It would store the OAuth configuration on the Foundry side. The personal consent had to be given by the user. No Notion token may be copied into the container or into Git.

## Criteria to move to the runtime

Record the following evidence without keeping tokens or sensitive consent links:

1. A connection using the official server and the personal identity.
2. A real consent link, a successful consent and resumption of the request.
3. Discovery of the exact tool names and a successful read of a chosen page.
4. Renewal compatible with the `default` scope and no local callback.

On failure, document the error and stop; do not add a substitute OAuth service. Until this evidence exists, keep Notion disabled in the deployment.

The code can be prepared and tested with simulated transports before this validation; only its cloud activation depends on the evidence above. The `direct|foundry` backends, per-request loading, filtering of prefixed names, write approvals and `FoundryCheckpointSaver` are implemented. Also verify the persistence of responses and user isolation: a checkpoint alone guarantees neither resumption through `previous_response_id` nor the single execution of a write. Test a read, an approval, a refusal and a resume after restart in the playground. The CD smoke test must stay independent of OAuth consent.

## The implemented backend and its configuration

`src/savant/tools/notion_foundry.py` uses `AzureAIProjectToolbox` and loads the tools in the asynchronous nodes, under the host's current context. There is no toolbox call at startup, no cache of tools between users and no user call identifier built or remembered by the application. The lists must contain the full names the toolbox returns, for example `notion___<exact-name>`: there is no automatic prefix removal. Tools outside the lists are not exposed. Listed writes and selected tools marked `require_approval=always` go through the same interruption.

For an existing, authorized toolbox, configure:

```dotenv
NOTION_MCP_ENABLED=true
NOTION_BACKEND=foundry
NOTION_TOOLBOX_NAME=<toolbox-name>
FOUNDRY_PROJECT_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>
NOTION_READ_TOOL_NAMES=<validated-full-names>
NOTION_WRITE_TOOL_NAMES=<validated-full-names>
```

Foundry provides the project endpoint in the cloud. The checkpointer uses `user_isolation=True`. The official host manages the storage of responses and conversation chains; do not replace it with in-memory storage.

When consent is required during discovery, the SDK returns a synthetic `oauth_consent_required` tool. The graph displays its instructions without calling the model and retries discovery on the next request. This path does not itself emit a native `oauth_consent_request` item: the playground's behaviour and the resumption through `previous_response_id` remained to be verified. The SDK may log the consent link: treat those logs as sensitive. A consent that expires during a tool call can be returned as a tool error; re-authenticate then retry explicitly, without automatically rerunning a write. There is no single-execution guarantee.

Create the connection and the toolbox in the Foundry portal or the Foundry toolkit, with personal OAuth and only the official server, after an explicit agreement. Discover and verify the read tools before authorizing writes. `NOTION_MCP_ENABLED` stays explicitly `false` in the manifest until validation, and its lists stay empty: fill them with the validated names at activation time. Publishing the code through CI/CD does not validate OAuth and does not enable Notion.

## Compatibility: additional research of 2 October

Notion requires Authorization Code with PKCE, secure storage and token renewal. Its client registration and Foundry's HTTPS callback still had to be matched. The [Microsoft list of managed OAuth connectors](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/model-context-protocol) does not contain Notion: follow the custom OAuth path.

A [discussion in a Microsoft repository](https://github.com/microsoft-foundry/new-foundry-portal/issues/109) reports difficulties with public clients; an answer from the team says they believe PKCE is supported, without operational confirmation for Notion. That discussion therefore shows neither compatibility nor incompatibility. The next evidence needed stayed a custom OAuth connection, the user's consent and a real read, before activating the backend.

## Connecting a toolbox in general mode

The general `TOOLBOX_ENDPOINT` mode, configured in `azure.yaml`, exposes all the tools of a toolbox; it works with `NOTION_MCP_ENABLED=false`, which disables only the Notion-specific backend described above. See [toolbox.md](toolbox.md).

Real discovery of a toolbox version reached Foundry and obtained a consent request for the Notion connection. Consent stays manual, and no Notion read or write is validated by this connection. CD tests the runtime and the model separately; see [cd-workflow.md](cd-workflow.md).
