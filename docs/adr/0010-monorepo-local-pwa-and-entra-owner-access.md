# ADR-0010: One repository for agent, backend and web client; run the web client locally; restrict the owner with Entra ID

- **Status:** Accepted
- **Date:** 2026-10-31
- **Tags:** agent, azure, security, infra
- **Amends:** the Static Web Apps assumption in [SDD-001](../design/sdd-001-mvp-scope-and-use-cases.md) and [SDD-002](../design/sdd-002-architecture-and-azure-infrastructure.md). [ADR-0009](0009-bff-owns-user-facing-oauth.md) stays accepted.

## Context

- Azure Static Web Apps is impossible on the Azure for Students subscription. The region policy allows only `switzerlandnorth`, `polandcentral`, `spaincentral`, `norwayeast` and `italynorth`, while Static Web Apps exists only in `centralus`, `eastus2`, `westus2`, `westeurope` and `eastasia`. The intersection is empty (decision of 2026-10-30; see [SPEC-002](../design/spec-002-azure-for-students-constraints.md)).
- The web client had its own repository, justified by its own Static Web Apps deployment. That reason disappeared, and the contract between the backend and the web client (owner check, routes, error handling) was changing across two repositories at once.
- The backend's owner check expected the Static Web Apps `owner` role in `x-ms-client-principal`, a role that exists only behind Static Web Apps.

## Decision

- **One repository.** The web client lives in the `pwa/` folder of the main repository.
- **The web client is validated by CI only.** `.github/components.json` declares `pwa/**` as non-runtime and adds a CI-only check: a web-client change runs the Node job (install, audit, tests, build) and never deploys the agent or publishes the backend. `.agentignore` excludes `pwa/` from the hosted-agent package.
- **The web client runs locally.** There is no Azure hosting in the first milestone. The hosting decision stays open.
- **Owner access is Microsoft Entra ID through Container Apps authentication (Easy Auth)** on the backend, with anonymous requests allowed so the readiness and callback routes stay public. "Assignment required" limits the app to the owner. The backend compares the `X-MS-CLIENT-PRINCIPAL-ID` header with the configured owner object ID and requires the `aad` provider. Details in [ADR-0011](0011-entra-easy-auth-on-the-bff.md).
- **Local token proxy.** The web client's development server proxies `/api` to the backend and adds the owner's token from `az account get-access-token`. The token never reaches the browser.
- **Backend to agent.** The backend's managed identity holds the Foundry Agent Consumer role on the agent only.
- **Three distinct identifiers:** the owner object ID (access control), the fixed owner key shared by the backend and the agent (token storage key), and the app registration client ID (token audience).

## Consequences

**Positive**

- A contract change touches the backend and the web client in a single pull request.

**Negative / risks**

- Any change to `.github/components.json` or `.agentignore` is a runtime change for both components, so such a pull request triggers an agent deployment and a backend publication, even when the runtime code is identical.
- The repository must not be renamed while the OIDC federated credential is bound to its name.
- The Content-Security-Policy and security headers that a Static Web Apps config file used to carry must be configured by whichever host is chosen later.
- The web-client routes of the backend stay disabled until the agent URL is set, and it must be set only after Easy Auth is active, otherwise the identity header could be forged.
- Open points when this was decided: whether the Azure CLI client must be pre-authorized on the API exposed by the app registration, and whether Easy Auth works with a voice WebSocket (later made moot by [ADR-0015](0015-browser-voice-interface-contract.md): the browser talks to Speech directly).

## Related

[SDD-001](../design/sdd-001-mvp-scope-and-use-cases.md), [SDD-002](../design/sdd-002-architecture-and-azure-infrastructure.md), [SDD-004](../design/sdd-004-continuous-integration-and-delivery.md), [ADR-0009](0009-bff-owns-user-facing-oauth.md), [ADR-0011](0011-entra-easy-auth-on-the-bff.md)
