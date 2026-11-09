# ADR-0020: Use Entra ID and managed identities everywhere; keep the few secrets in Key Vault

- **Status:** Accepted
- **Date:** 2026-11-09 (recorded retrospectively; the principle was applied from the first Azure resource)
- **Tags:** security, azure, infra

## Context

A public-facing personal agent holds powerful credentials by nature (a workspace token, an SSH key, access to models and data). Long-lived keys in environment variables, repositories or CI settings are the usual way such a project leaks.

## Decision

- **No API keys.** Models, Azure AI Search, Cosmos DB, Blob Storage and Azure Speech are accessed with **Microsoft Entra ID**. Local development uses the developer's own Azure session through `DefaultAzureCredential`. Account keys are disabled where the service allows it (Cosmos DB, for example).
- **Managed identities** for every Azure workload: the hosted agent and the backend each have their own, with scoped RBAC roles (blob roles scoped to a container, for example).
- **Three secrets only**, all in **Key Vault**: the Notion token encryption key, an optional SSH private key and the Easy Auth client secret (a Container App secret). The agent reads Key Vault at use time. The backend image has no Key Vault SDK and receives its key through Container Apps secret references.
- **No Azure secret in CI.** GitHub Actions signs in with OpenID Connect (federated credential), limited to the `main` branch.
- **Nothing sensitive in logs.** No ID, token, OAuth code or query string is ever logged.
- **No secrets in Git.** Local values live in an ignored `.env` and deployment values live in the Azure Developer CLI environment, which Git ignores. A test checks that `azure.yaml` carries no literal Azure value.

## Consequences

**Positive**

- There is nothing to rotate in the repository, nothing to leak from CI, and permissions can be audited per identity.

**Negative / risks**

- RBAC is more work than a key: every identity and role must be declared and granted.
- The hosted agent's identity only exists after its first deployment, so its roles are granted in a second step.
- Easy Auth's client secret expires after 365 days and must be renewed.

## Related

[ADR-0009](0009-bff-owns-user-facing-oauth.md), [ADR-0011](0011-entra-easy-auth-on-the-bff.md), [configuration reference](../configuration.md#secrets)
