# Notion MCP in Savant: the architecture choice

Documentary research of **6 October 2026**, from primary sources consulted on the web. No Azure call, OAuth registration, consent or authenticated Notion call was made. The cloud observations below date from **2 October**, from the local hand-over; they do not describe an Azure state read today. The decision that followed is [ADR-0009](adr/0009-bff-owns-user-facing-oauth.md): the backend owns OAuth and the tools stay in the hosted agent.

## Proposed decision (at the time)

**Qualify first the path Hosted Agent LangGraph, then Foundry Toolbox, then the official Notion MCP server.** It was already wired into Savant. Do a bounded qualification of the OAuth client and of user resumption, rather than immediately adding a backend that manages tokens. If a reproducible obstacle remains, move to a Notion MCP client on the backend side with its own OAuth and durable storage. This decision is an architecture recommendation, not an operational compatibility already proven.

A comfortable interface and a BFF do not necessarily change this choice: a BFF can carry the application's sessions, the streaming, the consent buttons and the confirmations, while leaving Foundry to manage Notion OAuth. "Add a backend" and "move Notion OAuth to this backend" are two distinct decisions.

## What the repository proves

[toolbox.md](toolbox.md), [notion-foundry.md](notion-foundry.md) and [notion-local.md](notion-local.md) and the local hand-over describe:

- Agent v12 and the model smoke test passed on 2 October; 45 local tests passed. The smoke test deliberately bypasses tool discovery.
- A consumer endpoint was configured. At the last inspection, v3 existed but `default_version` stayed `1`. Creating a version is not a promotion; do not diagnose the old error from v3 alone.
- The Notion consent was reached; context forwarded by the search parent: error `Unknown OAuth client`. No real read or write was demonstrated. This error suggests checking the client registration; it does not prove the exact cause.
- [notion_foundry.py](../src/savant/tools/notion_foundry.py) loads the tools in the request context, takes over the approval policies and keeps an MCP compatibility adapter. [approval.py](../src/savant/tools/approval.py) interrupts the call with name, arguments and identifier before execution.
- The local direct backend uses a local browser callback and in-memory tokens. It is a validation base, not a durable multi-user solution.

The older sections of `notion-foundry.md` that mention the absence of a connection must not be read as a current cloud inventory.

## What the official sources establish

Toolbox centralizes tools and exposes an MCP endpoint reusable across runtimes. That is a reason to keep this abstraction in Savant as long as it works. [Microsoft overview](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/toolbox-overview).

Microsoft documents `AzureAIProjectToolbox` for LangGraph. The consumer endpoint follows `default_version`; promotion changes the tools served without redeploying the agent. The runtime must apply `require_approval`: the Toolbox MCP endpoint does not itself block calls that require approval. [Hosted Agent and Toolbox](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/use-toolbox-hosted-agent).

Foundry distinguishes the agent's identity toward Toolbox from the user's identity toward the service. OAuth on the connection manages acquisition, injection and renewal. The Hosted call's context must be forwarded; the managed identity of the BFF alone does not represent its user. OAuth consumers need the **Foundry Agent Consumer** role and the same Entra tenant as the project; cross-tenant exchange is not supported in this flow. [Toolbox authentication](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/tool-authentication).

Custom OAuth needs a client ID; the secret is optional depending on the client. The callback is provided after configuration. The documentation explains `oauth_consent_request`, then the continuation with `previous_response_id`. It provides no proof here that Notion's automatic DCR or PKCE works in this configuration. [Foundry MCP authentication](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/mcp-authentication).

The [public Notion metadata](https://mcp.notion.com/.well-known/oauth-authorization-server) announces `/authorize`, `/token`, `/register`, `authorization_code`, `refresh_token`, PKCE `S256`, the client methods `none`, `client_secret_basic`, `client_secret_post`, the scope `default` and support for Client ID Metadata Documents (`client_id_metadata_document_supported`). Microsoft generically recommends `offline_access`, but it is not announced here: do not add it without provider validation.

Notion requires an OAuth client with PKCE, refresh and secure storage. Its guide describes DCR and confirms CIMD as an alternative. The credentials of a REST integration must therefore not be presumed valid for the MCP server. Web tokens stay on the server side; rotation requires atomic persistence and a serialized refresh. `invalid_grant` leads to reconnecting. [Notion client guide](https://developers.notion.com/guides/mcp/build-mcp-client).

**CIMD supported by Notion does not mean CIMD supported by Foundry.** Likewise, OAuth being available on both sides does not prove they interoperate.

## Comparison applied to Savant

| Option | Gain for Savant | Work and limit |
| --- | --- | --- |
| Hosted Agent and Toolbox | Reuses the existing path; OAuth management delegated; tools changeable by promotion | Prove Notion, PKCE, refresh and resumption; a compatible Entra population |
| Interface and BFF in front of Foundry | Sign-in, progress and confirmations adapted to the user; a future voice channel | Preserve the identity and the IDs; does not alone solve an incompatible OAuth client |
| A backend that is a direct Notion MCP client | Control of the callback, PKCE, application identity and the reconnection experience | Build token storage, rotation, isolation, revocation, errors and operations |

This table expresses design consequences deduced from the official constraints and the code, not measurements of cost or latency. Adding a network layer offers no performance guarantee; measure the real flow before optimizing.

## The bounded qualification to do next

The research authorizes this report only. The following cloud changes stay subject to the learning framework of `AGENTS.md`.

1. Reread the default version and the connection actually served; compare with the expected Notion configuration. Rule out a wrong version first.
2. Check the connection's client ID, the real HTTPS callback and its Notion registration. A DCR pre-registration can in principle be enough, provided Foundry produces PKCE and a compatible token exchange. Resolve the callback before registering; do not invent a URL or reuse REST credentials.
3. Observe, without logging secrets, the useful parameters: callback, presence of `code_challenge_method=S256`, client method, scope. Check the exact error if the client stays unknown.
4. Have the user consent personally, resume the request and read a chosen page. Check the real result, then another isolated user's access if the product targets several people.
5. Check renewal and reconnection, then a limited write with approval, a refusal and a resume after restart. Keep non-secret IDs and expected results as evidence.

Stop the qualification if the callback or client cannot be configured, if PKCE is absent or incompatible, or if refresh or resumption fails durably with a verified configuration. Document the reproduction before choosing the direct backend; do not multiply Azure changes without evidence.

## Switching criteria and a comfortable experience

**Keep Toolbox** if reading, refresh, isolation and approvals pass, and if the intended users can use the Foundry tenant. A thin BFF can then display "Connect Notion", keep `previous_response_id` and the approval request identifier, and present the target and arguments before confirmation. The current code also returns consent instructions through a synthetic tool; check the format actually received, without assuming a native item identical to that of Prompt Agents.

**Choose the direct backend** if there is a reproducible OAuth incompatibility, persistent resumption limits, or a product aimed at external users whose identity does not fit the documented Entra flow. These needs can justify this option even before a technical failure. Reuse the existing transport, but replace the local callback and volatile memory with an HTTPS callback, isolated grants and durable encrypted storage. Choose a library after validating it with the existing lockfile; do not blindly copy an SDK example.

For voice, keep an accessible web interface for the browser consent and for displaying the proposed change. Provide a confirmation tied to the exact request, wait, refusal and expiry states, and a resume after a cut. This is a UX proposal; MCP alone does not provide these interactions.

OAuth consent authorizes access to Notion; it does not approve a given write. A resume or a timeout does not guarantee single execution: after an uncertain write result, reread and reconcile before rerunning. Neither a checkpoint nor the BFF proves an "exactly once" guarantee. These controls are to be qualified on the Savant runtime, independently of the choice of OAuth manager.
