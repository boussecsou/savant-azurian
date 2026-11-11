# ADR-0011: Protect the backend with Entra ID Easy Auth and an owner check

- **Status:** Accepted
- **Date:** 2026-10-31 (verified 2026-11-01)
- **Tags:** azure, security, infra
- **Implements:** the owner-access part of [ADR-0010](0010-monorepo-local-pwa-and-entra-owner-access.md)

## Context

The backend (a Container App) must accept calls from the owner's locally running web client only. Static Web Apps is not available, so the owner authenticates with Microsoft Entra ID and the Container Apps built-in authentication (Easy Auth) validates the token before the backend code runs. The backend reads `X-MS-CLIENT-PRINCIPAL-ID` and compares it with the owner object ID.

## Decision

### App registration

Created by the Azure portal ("Create new app registration"):

- single tenant, with an Application ID URI of the form `api://<client-id>`, version 2 access tokens and one exposed scope, `user_impersonation`;
- a client secret with a 365-day lifetime, stored by the portal as a Container App secret. It must be renewed before it expires. It is not used to validate bearer tokens, which uses Entra's public signing keys. The provider configuration requires it for the browser sign-in flow that this project does not use;
- **Azure CLI is pre-authorized** on `user_impersonation` (Expose an API, Authorized client applications, application ID `04b07795-8ddb-461a-bbee-02f9e1bf7b46`). Without it, `az account get-access-token --resource api://…` fails with `AADSTS65001` and `az login --scope api://…/.default` fails with `AADSTS650057`.

### Easy Auth on the Container App

- Adding the Microsoft identity provider under Authentication is what enables Easy Auth. There is no separate switch.
- **Restrict access: allow unauthenticated access** (`AllowAnonymous`), so `/readiness` and `/oauth/notion/callback` stay public. The backend refuses protected routes itself, with `401` when no identity header is present.
- **Client application requirement: specific client applications**, limited to Azure CLI. Identity requirement: any identity. The allowed audience is the Application ID URI.
- The Microsoft Graph permissions were left at the default (`User.Read`): the flow is token-based and never an interactive browser sign-in, so no consent prompt happens.

### Access model

- **"Assignment required" is left disabled** on the enterprise application, because the tenant contains a single user, the owner. Consequence: any identity in the tenant could obtain a token for this API. The remaining controls are that Easy Auth accepts only tokens requested by Azure CLI, and that the backend returns `403` to any caller whose object ID differs from the owner's. **Revisit this decision if the tenant gains guests or other users.**
- **Backend to hosted agent.** The backend's managed identity holds **Foundry Agent Consumer** on the agent only (agent scope, least privilege). An agent-scope assignment only grants access to that agent's endpoint.
- **Sign-in method.** Security Defaults in the tenant block the device-code flow (`AADSTS530035`), so Azure CLI uses the browser flow (`az login` without `--use-device-code`). Security Defaults are not disabled.

## Verification (2026-10-31 and 2026-11-01)

| Check | Result |
| --- | --- |
| Callback route without a token | `400`: the public route works with Easy Auth on |
| `/readiness` | `200` (the very first request timed out; cause not established) |
| Token for the API audience | Obtained after pre-authorization, with the expected `aud`, `ver`, `azp` and `scp` claims |
| Fake token on `/readiness` | `200`: with `AllowAnonymous`, Easy Auth treats an invalid token as anonymous instead of rejecting it |
| Protected route, no token | `401` |
| Protected route, forged identity header and no token | `401` |
| Protected route, fake token | `401` |
| Protected route, owner token | `200` |

## Consequences

**Positive**

- Public routes keep working, and the web-client routes are enabled only after the three required settings exist.

**Negative / risks**

- Secret renewal is a recurring operation.
- The behaviour for invalid tokens depends on the backend code, because Easy Auth does not reject them in `AllowAnonymous` mode. That is why the backend check exists and fails closed.
- The configured issuer differs from the token's `iss` claim. A valid token is accepted in practice, so the configured issuer works, but a `401` for a valid token would point here.

**Order of activation**

1. Activate Easy Auth.
2. Set the owner key and the owner object ID.
3. Set the agent URL **last**. The backend refuses to start if the agent URL is set without the other two.

## Open points

- The chat path from the backend to the agent (`POST /api/chat`, with the Foundry Agent Consumer role) was not yet tested when this was written.

## Related

[ADR-0009](0009-bff-owns-user-facing-oauth.md), [ADR-0010](0010-monorepo-local-pwa-and-entra-owner-access.md), [SDD-002](../design/sdd-002-architecture-and-azure-infrastructure.md), [ADR-0020](0020-keyless-access-with-entra-and-key-vault.md), [deployment guide](../deployment.md#9-turn-on-easy-auth-azure-portal)
