# Direct Notion MCP: OAuth in the chat

First implemented on 6 October 2026 and completed with the semantic approval work. The [discovery and conversational confirmation policy](notion-semantic-approval.md) describes the current behaviour, the local evidence and the playground limits. The decision is recorded in [ADR-0009](adr/0009-bff-owns-user-facing-oauth.md).

The runtime calls the **official Notion MCP server**, independently of Foundry's custom MCP OAuth. The existing Azure OpenAI model and the LangGraph/Responses hosting are still used.

## The flow

1. A request needs Notion: the model calls `connect_notion` if no valid grant exists for the user identity provided by Foundry.
2. The graph returns a **Connect Notion** link, stores the request in its checkpoint and ends the reply. It does not wait for the browser.
3. Notion shows its consent screen and redirects to the HTTPS callback.
4. The callback validates the single-use OAuth state, exchanges the code with PKCE and keeps the tokens encrypted. Its page asks the user to return to the chat.
5. In **the same conversation**, write **"connected"**: the graph loads the authorized Notion tools and resumes the initial request. A confirmation message is not enough if the callback did not actually succeed.
6. Tools listed as writes go through the existing approval. OAuth consent and approval of a change are distinct.

A greeting does not trigger consent. The exact smoke test stays a real model call with no MCP discovery and no read of the OAuth store. The agent receives no Notion password. Tokens are never placed in messages or tool arguments; the consent link is personal.

## Local configuration

Install with `uv sync --locked --group dev`. In an uncommitted `.env`:

```dotenv
TOOLBOX_ENDPOINT=
FOUNDRY_PROJECT_ENDPOINT=
AZURE_AI_PROJECT_ENDPOINT=
NOTION_MCP_ENABLED=true
NOTION_BACKEND=direct
NOTION_MCP_URL=https://mcp.notion.com/mcp
NOTION_OAUTH_CALLBACK_URL=http://127.0.0.1:8090/oauth/notion/callback
NOTION_OAUTH_STORE_URL=sqlite:///tmp/sa2-notion-oauth/credentials.db
NOTION_LOCAL_USER_ID=local-dev
NOTION_TOOL_POLICY=dynamic
NOTION_READ_TOOL_NAMES=
NOTION_WRITE_TOOL_NAMES=
OAUTH_CALLBACK_PORT=8090
```

Add `NOTION_OAUTH_ENCRYPTION_KEY`, a Fernet key generated once (`uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`). Keep it in the secret configuration of **both processes**. Do not commit it, and do not replace it at every restart: it decrypts the existing grants.

In two terminals, from this repository:

```bash
uv run --locked python -m savant.oauth_callback
uv run --locked python main.py
```

The browser must be able to reach the callback on this machine. The local agent endpoint stays `/responses` on port 8088. Keep `previous_response_id` between the initial request and the "connected" message. A local test can remove `FOUNDRY_PROJECT_ENDPOINT` to use the in-memory checkpointer; in the cloud, conversations use the Foundry checkpointer with user isolation.

Dynamic discovery exposes every tool the server actually advertises. Only explicit read annotations allow automatic execution; any unknown or mutating operation asks for confirmation. The account's restrictions are still applied by Notion. The optional mode `NOTION_TOOL_POLICY=allowlist` restricts tools to the configured names; the read list cannot remove a write protection. An empty write list therefore does not impose a read-only mode under dynamic discovery.

## Cloud preparation

The code **provisions and deploys nothing**. `azure.yaml` prepares direct Notion for the next authorized deployment; changing the manifest does not change the currently hosted version.

The callback is a small independent ASGI application, started with `python -m savant.oauth_callback`. It exposes `GET /oauth/notion/callback` and `/readiness`. Do not assume Foundry publishes this route if the callback is simply added to the agent's container.

Reuse the HTTPS backend and the private Blob container. Both processes use:

```dotenv
NOTION_MCP_ENABLED=true
NOTION_BACKEND=direct
NOTION_OWNER_ID=<the owner's fixed key, identical for the backend and the agent>
NOTION_OAUTH_CALLBACK_URL=https://CALLBACK-HOST/oauth/notion/callback
NOTION_OAUTH_STORE_URL=https://STORAGE.blob.core.windows.net/PRIVATE-CONTAINER/notion-oauth.enc
NOTION_LOCAL_USER_ID=
```

### Shared key and identities

The backend receives `NOTION_OAUTH_ENCRYPTION_KEY` through a Container Apps secret reference (`secretRef`) backed by the Key Vault secret `notion-oauth-encryption-key` and the backend's user-assigned identity. It does not read Key Vault through the SDK: its image excludes `azure-keyvault-secrets`. The native Container Apps configuration uses the **ARM resource ID** of that identity. For the backend's Blob access, also set `NOTION_OAUTH_MANAGED_IDENTITY_CLIENT_ID` to its **client ID**. The Bicep template does both ([deployment guide](deployment.md)).

The Hosted Agent accepts these **non-secret** parameters:

```dotenv
NOTION_OAUTH_KEY_VAULT_URL=https://<vault>.vault.azure.net
NOTION_OAUTH_KEY_VAULT_SECRET_NAME=notion-oauth-encryption-key
NOTION_OAUTH_MANAGED_IDENTITY_CLIENT_ID=<the agent's instance_identity.client_id>
```

These parameters replace copying the key into the agent's environment. When the vault is configured, the SDK reads the secret when the direct Notion backend starts, validates it as a Fernet key, then closes the client and its credential. An error refuses startup; it never falls back to an environment key. The URL and the secret name must be set together. Without these parameters, the environment key stays available for local development. The backend ignores these vault parameters and always requires its injected key.

With an explicit client ID, Key Vault and Blob use `ManagedIdentityCredential(client_id=...)`, with no fallback chain. In Foundry, take `instance_identity.client_id` of **the agent**, not the project's identity nor the `principal_id` used for RBAC. Without a selector, local development uses `DefaultAzureCredential` (the existing Azure CLI session, in particular). In production, set the selector of each component.

Both components must point to the same key and the same blob. Do not rotate the key by creating a new secret version without a migration: Fernet could no longer decrypt the existing tokens. The key is loaded once when the agent starts. Native Container Apps synchronization can restart the backend after a rotation; coordinate both components. Application errors are neutral; do not enable the SDK's HTTP traces.

The capabilities and their documented limits are detailed in [the Key Vault research](research-bff-key-vault.md), with the Microsoft sources.

### Backend image and local check

```bash
docker build --file Dockerfile.bff --tag sa2-bff:ci .
python3 scripts/smoke_test_bff.py sa2-bff:ci
```

`Dockerfile.bff` reuses Python 3.13 and `uv.lock` and starts `python -m savant.oauth_callback` on `0.0.0.0:8090` as a non-root user. The Docker context is limited to the code and the dependency manifests; no `.env`, CLI state or data file is copied. Secrets are supplied at runtime only. In Container Apps, configure an HTTP `/readiness` probe on 8090; the Docker HEALTHCHECK does not replace the Container Apps configuration.

The script and CI test the real image through a port published on loopback, a synthetic key and a temporary SQLite file. They check HTTP 200 and the absence of the Key Vault SDK. They prove neither RBAC, nor Key Vault injection, nor Blob access in Azure. `/readiness` proves the service is started; it makes no Notion or Blob request.

Both Azure identities must be able to reach the container through managed identity (`Storage Blob Data Contributor`, at container scope). Fernet encryption also protects the content before upload. Blob leases serialize changes and refresh between instances. No SAS and no permanent Azure secret is expected in the URL. A single document suits this prototype; that choice serializes all connections and is not a high-concurrency architecture.

Change the agent manifest variables **before its next deployment**. Start with `TOOLBOX_ENDPOINT` empty to isolate Notion. Other Toolbox tools can then coexist with this direct backend; an old Notion OAuth source in a Toolbox could still cause its own consent. The graph does not mix the tokens or approvals of the two integrations.

The callback disables Uvicorn access logs because their URL contains the OAuth code. Also configure the proxy and the telemetry of the future hosting so these query strings are not kept. The HTML includes no code, state or token.

The user key comes from the **trusted** context of the Hosted Agent, never from the prompt, the thread ID or arguments supplied by the model. If it is missing, Notion access is refused. The local identity is not accepted under Foundry hosting. The callback attaches the tokens to the user of the initial transaction and refuses an expired, unknown or reused state.

## Validation and limits

The tests simulate the OAuth and MCP providers: link and PKCE, callback return, resumption, encryption, isolation, expiry, refusal, replay, rotation, and approval or refusal of a write. They do not prove a real consent or a cloud read. The personal consent, a chosen read, the refresh, and an approved then refused sandbox write must be validated after the authorized configuration and deployment.

The server renews tokens near their expiry. `invalid_grant` clears the grant and asks for consent again. An MCP discovery that returns 401 also invalidates the grant. No automatic retry of a write after a timeout is introduced; reread and reconcile an uncertain result. A checkpoint is not an "exactly once" guarantee.

The web client can reuse this same callback and trigger the next turn after connection. The playground version deliberately asks for "connected".

Sources: [Notion OAuth client](https://developers.notion.com/guides/mcp/build-mcp-client), [official tools](https://developers.notion.com/guides/mcp/mcp-supported-tools), [Hosted Agent contract](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agent-contract).
