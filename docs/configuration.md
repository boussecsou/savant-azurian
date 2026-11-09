# Configuration reference

Every setting of Savant Azurian, in one place. A test (`tests/test_config_docs.py`) fails when the code, `.env.example`, `azure.yaml`, or the workflows use a variable that this page does not describe.

## Where a value lives

| Kind | Lives in | Rule |
| --- | --- | --- |
| Local development values | `.env` (copied from `.env.example`) | Git ignores it. Never commit it. |
| Deployment values (URLs, names, IDs) | the azd environment, `.azure/<env>/.env` | Set with `azd env set`. `azure.yaml` reads it as `${NAME}`. Nothing personal is hard-coded in the repository. |
| CI values | GitHub repository variables | Same names as the azd variables. Copied by `scripts/setup/github-variables.sh`. |
| Secrets | Azure Key Vault | Never in Git, `.env`, the azd environment or GitHub. See [Secrets](#secrets). |

The **Scope** column says who reads a variable: `agent` (the hosted agent, also local), `bff` (the web backend), `local` (local development only), `script` (a script in `scripts/`), `azd` (the Azure Developer CLI), `ci` (GitHub Actions), `platform` (injected by Foundry), `sdk` (read by an Azure SDK, not by this code). The drift test requires the scopes `agent`, `bff`, `local` and `script` to match what the code really reads.

## Model and agent runtime

Read by `Settings.from_env()` (`src/savant/config.py`). It validates everything at startup and fails fast with a `RuntimeError`; only the first two are always required.

| Variable | Scope | Secret | Default | Set in | Description |
| --- | --- | --- | --- | --- | --- |
| `AZURE_OPENAI_BASE_URL` | agent | no | (required) | azd output; `.env` | Azure OpenAI v1 base URL, ending in `/openai/v1/`. The client uses the Responses API and Entra ID, never a key. |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | agent | no | (required) | azd output; `.env` | Name of the chat model *deployment* (not the model name). |
| `PORT` | agent | no | `8088` | `.env` | Port of the local Responses server. |
| `AZURE_AI_PROJECT_ENDPOINT` | agent | no | empty | azd output; `.env` | Foundry project endpoint. Alias of `FOUNDRY_PROJECT_ENDPOINT`; required for cloud chat OAuth (durable conversations). |
| `FOUNDRY_PROJECT_ENDPOINT` | agent | no | empty | `.env` | Same value as `AZURE_AI_PROJECT_ENDPOINT`. The platform injects `FOUNDRY_*` variables in the hosted container: never set them in `azure.yaml`. |
| `MODEL_REASONING_EFFORT` | agent | no | `low` | `.env`; `azure.yaml` | `minimal`, `low`, `medium`, `high`, or empty to keep the provider default. Lower is faster. |
| `MODEL_TIMEOUT_SECONDS` | agent | no | `90` | `.env` | Timeout of one model call, in seconds, in (0, 240]. |
| `MODEL_MAX_RETRIES` | agent | no | `2` | `.env` | Client retries of a model call, 0 to 5. |
| `MODEL_FAST_PATH` | agent | no | `true` | `.env` | `true`/`false`. A first call without tools answers simple turns and hands the rest to the full agent. |
| `SEMANTIC_APPROVAL_MODEL` | agent | no | empty | `.env` | Deployment that judges consent. Empty uses the main model. Changing it requires re-measuring pass^k (`docs/notion-semantic-approval.md`). |
| `SEMANTIC_APPROVAL_TIMEOUT` | agent | no | `10` | `.env` | Seconds the consent judge may take, in (0, 30]. |
| `TOOLBOX_ENDPOINT` | agent | no | empty | azd output; `.env` | Foundry Toolbox MCP endpoint (`.../toolboxes/<name>/mcp?api-version=v1`). Web search and code interpreter. |

## Notion

Notion OAuth authorizes a workspace; the conversational consent authorizes one operation. Neither replaces the other.

| Variable | Scope | Secret | Default | Set in | Description |
| --- | --- | --- | --- | --- | --- |
| `NOTION_MCP_ENABLED` | agent | no | `false` | `azure.yaml`; `.env` | Turns the Notion tools on. |
| `NOTION_BACKEND` | agent | no | `direct` | `azure.yaml`; `.env` | `direct` (OAuth in the chat, production) or `foundry`. |
| `NOTION_MCP_URL` | agent | no | `https://mcp.notion.com/mcp` | `azure.yaml`; `.env` | Official Notion MCP endpoint. Chat OAuth rejects any other value. |
| `NOTION_TOOL_POLICY` | agent | no | `dynamic` | `azure.yaml`; `.env` | `dynamic`: only a tool with a read-only hint runs without consent. `allowlist` can only add protection. |
| `NOTION_READ_TOOL_NAMES` | agent | no | empty | `.env` | Comma-separated tool names treated as reads (allowlist mode). |
| `NOTION_WRITE_TOOL_NAMES` | agent | no | empty | `.env` | Comma-separated tool names always protected. A name cannot be in both lists. |
| `NOTION_TOOLBOX_NAME` | agent | no | `sa2-notion-tools` | `.env` | Toolbox name for `NOTION_BACKEND=foundry` only. |
| `NOTION_OAUTH_CALLBACK_URL` | agent | no | empty | azd output; `.env` | HTTPS URL of the BFF callback, path `/oauth/notion/callback` (HTTP loopback allowed locally). |
| `NOTION_OAUTH_STORE_URL` | agent | no | empty | azd output; `.env` | Blob URL of the encrypted token store. Agent and BFF must share it. |
| `NOTION_OAUTH_ENCRYPTION_KEY` | local | yes | empty | `.env` (never committed) | Encryption key of the token store. Locally you set it. In the cloud the agent reads the Key Vault secret itself; the BFF receives it as this variable, injected by Container Apps from the same Key Vault secret (secret reference), so you never type it. |
| `NOTION_OAUTH_KEY_VAULT_URL` | agent | no | empty | azd output (`KEY_VAULT_URL`) | Vault that holds the encryption key. |
| `NOTION_OAUTH_KEY_VAULT_SECRET_NAME` | agent | no | `notion-oauth-encryption-key` | `azure.yaml` | Name of that Key Vault secret. |
| `NOTION_OAUTH_MANAGED_IDENTITY_CLIENT_ID` | agent | no | empty | `azd env set` after the first deploy | Client ID of the identity that reads the vault. For the hosted agent: `instance_identity.client_id`, never inferred from the principal ID. |
| `NOTION_OWNER_ID` | agent | no | empty | `azd env set` | Fixed server-side key of the single owner (any stable string, for example a GUID you generate once). Same value on the agent and the BFF. Required in the cloud. It is a storage key, not a Notion ID. |
| `NOTION_LOCAL_USER_ID` | local | no | empty | `.env` | Owner key for the local loopback test only. |
| `NOTION_IDENTITY_DIAGNOSTICS` | agent | no | `false` | `.env` | Extra, redacted identity diagnostics while debugging the Foundry call identity. |

## SSH tool (optional, all or nothing)

Set all five of `SSH_HOST`, `SSH_USER`, `SSH_HOST_KEY`, `SSH_KEY_VAULT_URL`, `SSH_KEY_SECRET_NAME`, or none. A partial set stops the agent at startup. `scripts/setup/ssh-setup.sh` prepares them. See `docs/ssh-tool.md`.

| Variable | Scope | Secret | Default | Set in | Description |
| --- | --- | --- | --- | --- | --- |
| `SSH_HOST` | agent | no | empty | `azd env set` | Host name or IP of the Linux VM. |
| `SSH_PORT` | agent | no | `22` | `.env` | SSH port. |
| `SSH_USER` | agent | no | empty | `azd env set` | Dedicated Unix account the agent uses. |
| `SSH_HOST_KEY` | agent | no | empty | `azd env set` | Pinned public host key line (`ssh-ed25519 AAAA...`). No trust on first use. |
| `SSH_KEY_VAULT_URL` | agent | no | empty | `azd env set` | Vault holding the private key. |
| `SSH_KEY_SECRET_NAME` | agent | no | empty | `azd env set` | Key Vault secret with the private key (the key is never a file or a variable). |
| `SSH_CONNECT_TIMEOUT` | agent | no | `10` | `.env` | Connect timeout, seconds. |
| `SSH_COMMAND_TIMEOUT` | agent | no | `30` | `.env` | Command timeout, seconds. |

## Project documents (Azure AI Search)

The agent only gets `search_documents` when `SEARCH_ENDPOINT` is set. The project filter is applied by the server, never by the model. See `docs/search-documents.md`.

| Variable | Scope | Secret | Default | Set in | Description |
| --- | --- | --- | --- | --- | --- |
| `SEARCH_ENDPOINT` | agent | no | empty | azd output | `https://<service>.search.windows.net`. Also read by the BFF. |
| `SEARCH_INDEX` | agent | no | `sa2-docs` | `azure.yaml`; `.env` | Index name. Also read by the BFF and the setup script. |
| `SEARCH_INDEXER` | bff | no | `sa2-docs-indexer` | `.env` | Indexer the BFF runs after an upload. |
| `SEARCH_STORAGE_RESOURCE_ID` | script | no | (required by the script) | azd output | Resource ID of the storage account the indexer reads (`scripts/search_setup.py`). |
| `SEARCH_EMBEDDING_ENDPOINT` | script | no | (required by the script) | azd output | Endpoint of the account that hosts the embedding deployment. |
| `SEARCH_EMBEDDING_DEPLOYMENT` | script | no | (required by the script) | azd output | Embedding deployment name. |
| `SEARCH_EMBEDDING_MODEL` | script | no | `text-embedding-3-small` | `.env` | Embedding model; sets the vector dimensions. |
| `SEARCH_DOCUMENTS_CONTAINER` | script | no | `documents` | `.env` | Blob container the indexer reads. |

## BFF (backend for the web interface)

Read by `savant.oauth_callback` and `savant.bff_api`. Without `COSMOS_ENDPOINT` there is no `/api/projects` or `/api/sessions`; without `AGENT_RESPONSES_URL` there is no `/api/chat`.

| Variable | Scope | Secret | Default | Set in | Description |
| --- | --- | --- | --- | --- | --- |
| `AGENT_RESPONSES_URL` | bff | no | empty | `azd env set`, last | `/responses` endpoint of the hosted agent. Set it last: the BFF refuses to start if it is set without `NOTION_OWNER_ID` and `BFF_OWNER_OBJECT_ID`, and only after Easy Auth works. |
| `BFF_OWNER_OBJECT_ID` | bff | no | empty | `azd env set` | Entra object ID of the owner. The BFF returns `403` to any other caller. |
| `PWA_ORIGIN` | bff | no | empty | `azd env set` | Origin of the web interface for CORS (for example `http://localhost:5173`). |
| `OAUTH_CALLBACK_PORT` | bff | no | `8090` | `Dockerfile.bff` | Port the BFF listens on. |
| `SPEECH_ENDPOINT` | bff | no | empty | azd output | Azure AI Services custom-domain origin. Both Speech values or neither. |
| `SPEECH_REGION` | bff | no | empty | azd output | Region of that resource. |
| `COSMOS_ENDPOINT` | bff | no | empty | azd output | Cosmos DB endpoint. Turns projects and sessions on. |
| `COSMOS_DATABASE` | bff | no | `sa2` | `.env` | Cosmos DB database name. |
| `DOCUMENTS_ACCOUNT_URL` | bff | no | empty | azd output | Blob endpoint for project documents. With `SEARCH_ENDPOINT` it turns uploads on. |
| `DOCUMENTS_CONTAINER` | bff | no | `documents` | `.env` | Blob container for project documents. |
| `AZURE_CLIENT_ID` | sdk | no | empty | the Container App | Selects the BFF's user-assigned identity for `DefaultAzureCredential`. Read by the Azure SDK, not by this code. |

## Injected by the platform or by CI

Never put these in `.env` or `azure.yaml`. They are listed so the drift test can tell them from real configuration.

| Variable | Scope | Secret | Default | Set in | Description |
| --- | --- | --- | --- | --- | --- |
| `FOUNDRY_HOSTING_ENVIRONMENT` | platform | no | set in the hosted container | Foundry | Tells the code it runs as a Hosted Agent: a loopback OAuth callback is refused and the Foundry call identity is required. |
| `DEPLOYED_AGENT_VERSION` | ci | no |  | `cd.yml` | Agent version the smoke test must observe. |
| `GITHUB_EVENT_NAME` | ci | no |  | GitHub Actions | Used by `scripts/release_plan.py`. |
| `GITHUB_OUTPUT` | ci | no |  | GitHub Actions | Step outputs file. |
| `GITHUB_REPOSITORY` | ci | no |  | GitHub Actions | `owner/name` of the repository. |
| `GITHUB_RUN_ID` | ci | no |  | GitHub Actions | Current run, used to find the previous release checkpoint. |
| `GITHUB_STEP_SUMMARY` | ci | no |  | GitHub Actions | Step summary file. |
| `SOURCE_SHA` | ci | no |  | `publish-bff.yml` | Commit the BFF image is built from. |
| `IMAGE_REPOSITORY` | ci | no | `sa2-bff` | `publish-bff.yml` | Repository name of the BFF image in the registry. |
| `PUBLISH_V1` | ci | no | `false` | `publish-bff.yml` | Manual escape hatch for the first image publication. |

## azd environment

Set with `azd env set NAME value`. The values live in `.azure/<env>/.env`, which Git ignores. `azure.yaml`, the deployment workflow and the scripts in `scripts/setup/` read them. The other values `azure.yaml` uses (such as `TOOLBOX_ENDPOINT` or `SEARCH_ENDPOINT`) are described in the sections above.

| Variable | Scope | Secret | Default | Set in | Description |
| --- | --- | --- | --- | --- | --- |
| `AZURE_SUBSCRIPTION_ID` | azd | no | (required) | `azd env set` | Target subscription. |
| `AZURE_TENANT_ID` | azd | no | (required) | `azd env set` | Entra tenant. |
| `AZURE_LOCATION` | azd | no | (required) | `azd env set` | Azure region. Pick one that offers your chat model and hosted agents. |
| `AZURE_AI_PROJECT_ID` | azd | no |  | `azd env set` | ARM ID of the Foundry project. |
| `KEY_VAULT_NAME` | azd | no |  | `azd env set` | Key Vault name, used by the setup scripts. |
| `KEY_VAULT_URL` | azd | no |  | `azd env set` | Key Vault URL. Read by `azure.yaml` for the Notion encryption key. |
| `ACR_NAME` | azd | no |  | `azd env set` | Container registry name. Also a GitHub variable for `publish-bff.yml`. |
| `OIDC_CLIENT_ID` | azd | no |  | `azd env set` | Client ID of the identity GitHub Actions signs in with. It becomes the GitHub variable `AZURE_CLIENT_ID`. |

## GitHub repository variables

Configuration only, never secrets: GitHub signs in to Azure with OpenID Connect. `scripts/setup/github-variables.sh` copies them from the azd environment. The deployment workflow passes the ones `azure.yaml` reads to `azd env set`; the other workflows read these directly.

| Variable | Scope | Secret | Default | Set in | Description |
| --- | --- | --- | --- | --- | --- |
| `AZD_ENV_NAME` | ci | no | `savant-ci` | GitHub variable | Name of the azd environment the CD workflow creates on the runner. |
| `BFF_AUTO_PUBLISH` | ci | no | unset | GitHub variable | `true` publishes the BFF image automatically after a green CI on `main`. |

## Secrets

Only three secrets exist. None is a variable.

| Secret | Where | Who reads it | Created by |
| --- | --- | --- | --- |
| Notion token encryption key | Key Vault secret `notion-oauth-encryption-key` | the agent and the BFF, with their managed identities | `scripts/setup/generate-notion-key.sh` |
| SSH private key (optional) | Key Vault secret `sa2-ssh-private-key` | the agent, at use time | `scripts/setup/ssh-setup.sh` |
| Easy Auth client secret | Container App secret | Container Apps | the Azure portal when you add the identity provider (valid 365 days, renew it) |

No Azure secret is stored in GitHub. No API key exists: models, Search, Cosmos DB, Storage and Speech all use Entra ID.
