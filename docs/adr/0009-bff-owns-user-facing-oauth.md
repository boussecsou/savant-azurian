# ADR-0009: The Container Apps backend owns user-facing OAuth; tools stay in the hosted agent

- **Status:** Accepted
- **Date:** 2026-10-06
- **Tags:** agent, azure, security, infra

## Context

Notion has to become the first real tool of the cloud hosted agent. The official Notion MCP server authenticates clients through Dynamic Client Registration (DCR) or a Client ID Metadata Document. A Foundry Toolbox with custom OAuth expects a pre-registered client ID. Connecting the two is possible only through an undocumented workaround (a manual registration with the Foundry redirect URL), with unverified PKCE, client lifetime and refresh behaviour, and no public evidence of a working setup.

The direct path was already implemented and tested end to end locally: a direct chat graph, an OAuth module and a callback service. It needs a public HTTPS callback, a shared encrypted token store and a shared encryption key.

[SDD-002](../design/sdd-002-architecture-and-azure-infrastructure.md) already targets `web client → backend (Container Apps) → hosted agent`, with the backend owning authentication, session, conversation identifier, rate limiting and API gateway. Further connectors will need the same consent pattern, while SSH and retrieval need no user consent.

## Decision

- Run **one Azure Container App as the backend** (BFF). Its first job is to host the Notion OAuth callback; it later gains the consent start and status routes and the chat relay for the web client.
- The backend **owns user-facing flows only**: sign-in, session, OAuth consent and callbacks (Notion now, another connector later with the same pattern).
- **Tools stay in the hosted agent** (LangGraph): Notion, SSH and retrieval run in the graph, which keeps model routing ([ADR-0008](0008-main-llm-routes-tools-with-deterministic-feedback.md)), write approvals ([ADR-0017](0017-two-layer-authorization-for-notion-writes.md)) and graph observability.
- **Azure Blob Storage** holds the Fernet-encrypted OAuth tokens, shared by the backend and the agent.
- **Azure Key Vault** holds the encryption key and other secrets. The backend and the agent read them through their managed identities and RBAC ([ADR-0020](0020-keyless-access-with-entra-and-key-vault.md)).
- The Foundry Toolbox path for Notion is **not pursued**. A toolbox stays available for Foundry-native tools such as web search.

## Consequences

**Positive**

- One compute resource serves both the OAuth callback and the web backend. Nothing is thrown away.
- Adding another connector does not change the backend beyond an optional "connect" button reusing the Notion pattern.

**Negative / risks**

- **Owner-only scope (clarified 2026-10-20).** OAuth tokens are keyed by one stable, server-defined owner key, used consistently by the callback, the shared store and the agent, including the playground. There are no secondary accounts or delegated identities. A stable key is a lookup key, not authentication: access to the web client and the backend must be restricted to the owner ([ADR-0011](0011-entra-easy-auth-on-the-bff.md)).
- New resources to provision: a Container App and its environment, a storage account with a private container, a Key Vault and RBAC assignments.
- Continuous delivery cannot validate the Notion flow. Cloud validation of consent, a read, an approved write, a rejected write and token expiry stays a manual step.

## Related

[SDD-002](../design/sdd-002-architecture-and-azure-infrastructure.md), [SPEC-001](../design/spec-001-product-scope.md), [ADR-0008](0008-main-llm-routes-tools-with-deterministic-feedback.md), [ADR-0010](0010-monorepo-local-pwa-and-entra-owner-access.md), [Notion OAuth in the chat](../notion-chat-oauth.md)
