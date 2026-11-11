# Backend API for the web client

Owner-only routes added to the existing backend (BFF, `src/savant/bff_api.py`). The code **deploys and configures nothing in Azure**: without the variables below, the backend stays the OAuth callback alone, as before.

Context ([ADR-0010](adr/0010-monorepo-local-pwa-and-entra-owner-access.md)): Azure Static Web Apps is impossible on the Azure for Students subscription (region policy). The web client (`pwa/`) runs **locally**; the backend and the agent stay in Azure. The owner authenticates with **Microsoft Entra ID**, verified by the built-in authentication of Container Apps ("Easy Auth") in front of the backend ([ADR-0011](adr/0011-entra-easy-auth-on-the-bff.md)).

```text
Local web client ─▶ local dev proxy (adds the owner's Entra token)
                ─▶ backend (Container Apps + Easy Auth) ─▶ managed identity ─▶ Hosted Agent
```

## Routes

| Route | Role |
| --- | --- |
| `GET /api/oauth/notion/start` | Redirects (302) to the Notion consent for the owner. |
| `GET /api/oauth/notion/status` | `{"connected": true/false}`: does the owner have a usable grant? |
| `POST /api/chat` | Relays `{"message", "conversation_id"?}` to the Hosted Agent's `/responses`. |
| `POST /api/chat/stream` | The same relay, but the answer is forwarded as it is written (a `text/event-stream` stream, see below). |
| `POST /api/warmup` | Wakes the agent with its tool-free probe; `{"ready": true/false}`. |
| `GET /oauth/notion/callback`, `/readiness` | Unchanged, public (called by Notion and by Container Apps). |

### The `/api/chat/stream` stream

The same body and the same HTTP errors as `/api/chat` for anything that fails **before** the first byte (`401`, `403`, `422`, `502`, `504`). After that the backend forwards only a reduced vocabulary, one `data: {json}` line per event:

| Event | Content |
| --- | --- |
| `{"type":"delta","text"}` | A piece of the assistant's text. |
| `{"type":"tool","id","name","status":"running"}` | The agent calls a tool (name only). |
| `{"type":"tool","id","status":"done"}` | The tool returned its result. |
| `{"type":"done","conversation_id"}` | Normal end; the identifier to send back with the next message. |
| `{"type":"error","kind":"timeout"\|"upstream"}` | Failure after the stream started. |

Reasoning, tool arguments and their results (the owner's Notion data) are **never** relayed. The 120 s read timeout bounds the silence between two events, and the whole stream is cut at 220 s. A stream that stops without `done` or `error` is reported as `error`. The web client falls back to `/api/chat` if this route answers `404` (an older backend image).

### Warm-up: `/api/warmup`

Sends the agent the probe of `savant.health` (text duplicated in `bff_api.py`; a test guarantees it stays identical): a single model call, with no tool, no Notion and no OAuth. It wakes the agent's host and the model client before the first real message. The web client calls it on load, then when returning to the tab if the last wake-up is older than 4 minutes. It costs one short model call, and nothing guarantees that the session woken is the one that will serve the conversation: the web client's journal shows the warm-up duration so it can be measured.

The `start` and `status` routes also exist without a prefix (`/oauth/notion/start`) for direct calls (`curl` tests, a backend running locally).

`conversation_id` is the `id` of the agent's last response: the backend sends it back to the agent as `previous_response_id`. The web client keeps it and sends it with the next message; the first message has none. The response is `{"conversation_id", "reply"}`. Errors: `401` no identity, `403` not the owner, `422` invalid input, `502` agent error, `504` agent too slow (a 120 s timeout: the agent can take more than a minute for a Notion read, 66 s measured for a "list my tasks" request; it stays under the default request timeout of the Container Apps ingress, 240 s according to the documentation).

## The owner's identity

Three distinct identifiers, not to be confused:

| Identifier | Content | Role |
| --- | --- | --- |
| `BFF_OWNER_OBJECT_ID` | The owner's Entra *Object ID* (a GUID) | Access control to the backend's `/api` routes |
| `NOTION_OWNER_ID` | A fixed key chosen server-side | Storage key of the Notion token, the **same value** on the backend and the agent |
| The app registration client ID | The identity of the backend application in Entra | The token audience checked by Easy Auth |

- **Who can call.** Easy Auth validates the Entra token (signature, issuer, audience) before the backend, then adds the headers `X-MS-CLIENT-PRINCIPAL-ID` (the caller's *Object ID*) and `X-MS-CLIENT-PRINCIPAL-IDP` (`aad`). An external client cannot set these headers (Microsoft Learn, "Authentication and authorization in Azure Container Apps"). The backend compares them with `BFF_OWNER_OBJECT_ID`: header absent → `401`; another caller or another provider → `403` (fail closed). In Entra, "User assignment required" would assign only the owner: that is the first barrier, and the backend check is the second.
- **Anonymous requests allowed.** Easy Auth stays in "allow anonymous requests" mode so `/readiness` and `/oauth/notion/callback` stay public. Without a token, no identity header exists and the backend answers `401` itself.
- **Which `user_id` for Notion.** `NOTION_OWNER_ID`, a **fixed key** (single-owner scope). It is not a Notion identifier: the backend and the agent use it as the storage key of the token. The client can neither choose nor change it. The agent no longer compares it with the identity Foundry injects (`x-agent-user-id`): the endpoint is protected by Entra, so only authorized callers reach it. In the cloud, the platform's call identity (`x-agent-foundry-call-id`) is still required.
- **Local web client.** The development server of `pwa/` gets the token with `az account get-access-token --resource <api://…>` and adds it to the `/api` calls (see `pwa/README.md`). The browser never sees the token; CORS is unnecessary behind this proxy.
- CORS is enabled only if `PWA_ORIGIN` is set (a web client calling the backend from another origin). CORS does not replace the identity check above.

## Configuration (non-secret)

Environment variables of the backend's Container App:

```dotenv
NOTION_OWNER_ID=<a fixed key, identical to the agent's (azure.yaml)>
BFF_OWNER_OBJECT_ID=<the owner's Entra Object ID, for example 00000000-0000-0000-0000-000000000000>
AGENT_RESPONSES_URL=https://<account>.services.ai.azure.com/api/projects/<project>/agents/<agent>/endpoint/protocols/openai/responses?api-version=v1
PWA_ORIGIN=            # optional
```

- `BFF_OWNER_OBJECT_ID`: the user account's *Object ID* (portal → Entra ID → Users → Object ID, or `az ad signed-in-user show --query id -o tsv`). A GUID is mandatory as soon as `AGENT_RESPONSES_URL` is set; it is not a secret.
- `AGENT_RESPONSES_URL`: the Hosted Agent's `/responses` endpoint (HTTPS, host `*.azure.com`). The backend posts messages there with its managed identity (`NOTION_OAUTH_MANAGED_IDENTITY_CLIENT_ID`, scope `https://ai.azure.com/.default`). **Only this variable turns the routes on**; it then requires `NOTION_OWNER_ID` and `BFF_OWNER_OBJECT_ID`. A backend that has `NOTION_OWNER_ID` without this URL stays a plain callback. The agent's endpoint answers `400` (`Missing required query parameter: api-version`) without that parameter: the backend adds `api-version=v1` automatically when the URL has none, and keeps the one you give. A refusal from the agent is logged by its HTTP status alone (`chat_relay_failed status=400`), with no response body, URL or token; the client receives `502`.

## Before setting `AGENT_RESPONSES_URL` (security)

The backend trusts `X-MS-CLIENT-PRINCIPAL-ID`. Until Easy Auth is active on the Container App, its ingress is public and **anyone can forge that header** (an *Object ID* is not a secret). So set `AGENT_RESPONSES_URL` only **after** enabling Easy Auth and checking that a call without a token is refused.

## Commissioning status (verified on 2026-10-31)

**Verified**

- Public routes with Easy Auth on: `/readiness` answers `200` and `/oauth/notion/callback?state=x` answers `400`.
- A token obtained with `az account get-access-token --resource api://<client-id>` after pre-authorizing Azure CLI on the `user_impersonation` scope. Claims observed: `aud` = the client ID, `iss` = `login.microsoftonline.com/<tenant-id>/v2.0`, `ver` = `2.0`, `azp` = Azure CLI, `scp` = `user_impersonation`.
- With `AGENT_RESPONSES_URL`, `NOTION_OWNER_ID` and `BFF_OWNER_OBJECT_ID` set, on `/api/oauth/notion/status`: no token `401`, fake token `401`, a forged `X-MS-CLIENT-PRINCIPAL-ID` header without a token `401`, the owner's token `200`.
- A Hosted Agent version deployed by CD, with the Notion configuration and `NOTION_OWNER_ID`.

**Not verified**

- The `POST /api/chat` call and the Foundry Agent Consumer role of the backend identity on the agent (without that role, the agent answers `401`).
- Notion consent through `/api/oauth/notion/start` from the web client.
- Revocation, then reconnection of the Notion access.

## Azure setup (summary)

Manual steps, done in the portal; nothing is deployed by the repository. The [deployment guide](deployment.md#9-turn-on-easy-auth-azure-portal) has the full walkthrough.

1. **Identity provider.** Container App → *Authentication* → *Add identity provider* → *Microsoft* → *Create new app registration* (single tenant). The portal creates the app registration, its service principal (Enterprise application), the `api://<client-id>` URI, the `user_impersonation` scope and a client secret stored as a Container App secret. That secret is valid for 365 days: renew it.
2. **Authentication settings.** *Restrict access* = **Allow unauthenticated access** (otherwise `/readiness` and the Notion callback are blocked); *Client application requirement* = **specific client applications** with the Azure CLI ID `04b07795-8ddb-461a-bbee-02f9e1bf7b46`; *Identity requirement* = **any identity**.
3. **Pre-authorize Azure CLI.** App registration → *Expose an API* → *Authorized client applications* → the Azure CLI ID, with the `user_impersonation` scope checked. Without it, `az account get-access-token` fails with `AADSTS65001` and `az login --scope …/.default` with `AADSTS650057`.
4. **"Assignment required".** Not enabled, because the tenant has a single user. Documented residual risk: any identity of the tenant can obtain a token, but Easy Auth accepts only the tokens requested by Azure CLI and the backend refuses (`403`) any *Object ID* other than `BFF_OWNER_OBJECT_ID`.
5. **Azure CLI sign-in.** The tenant's *Security Defaults* block the device-code flow (`AADSTS530035`). Use `az login` in the browser, without `--use-device-code`.
6. **Backend to agent role.** *Foundry Agent Consumer* granted to the backend's managed identity on the agent's scope (least privilege).
7. **Container App variables.** Set `NOTION_OWNER_ID`, `BFF_OWNER_OBJECT_ID`, then `AGENT_RESPONSES_URL` **last**. If `AGENT_RESPONSES_URL` is set without the other two, the backend refuses to start.

## `curl` control tests

Run after `az login` (in the browser). `<client-id>` is the app registration's ID; do not publish a token, an *Object ID* or a tenant identifier.

```bash
BFF=https://<backend-fqdn>
APP=api://<client-id>
TOKEN=$(az account get-access-token --resource $APP --query accessToken -o tsv)
code() { curl -s -o /dev/null -m 25 -w "%{http_code}\n" "$@"; }

code $BFF/readiness                                   # 200
code "$BFF/oauth/notion/callback?state=x"             # 400
code $BFF/api/oauth/notion/status                     # 401: no token
code -H "Authorization: Bearer abc" $BFF/api/oauth/notion/status           # 401: fake token
code -H "X-MS-CLIENT-PRINCIPAL-ID: <object-id>" -H "X-MS-CLIENT-PRINCIPAL-IDP: aad" \
     $BFF/api/oauth/notion/status                     # 401: forged header, no token
code -H "Authorization: Bearer $TOKEN" $BFF/api/oauth/notion/status        # 200: the owner
```

With "Allow unauthenticated access", Easy Auth does not reject a fake token: it treats it as an anonymous request, without identity headers (so a fake token on `/readiness` gives `200`). It is the **backend** that refuses the protected routes (`401` without an identity). As long as `AGENT_RESPONSES_URL` is not set, every `/api/*` route answers `404` and these tests prove nothing about identity.
