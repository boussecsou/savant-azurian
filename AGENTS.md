# Savant Azurian: development guide

A single-owner personal agent (Python 3.13, LangGraph) hosted as a Foundry Hosted Agent, plus a FastAPI backend (BFF) for the Notion OAuth callback. Monorepo: agent, BFF and web client (`pwa/`, React + Vite). The web client runs locally; the BFF and the agent stay in Azure. The historical prototype is only a functional reference: do not migrate it as is.

This project uses the `microsoft-foundry` skill. Read it before changing a Hosted Agent, a Toolbox, a Foundry connection, an `azd` command or CI/CD.

The design record is in [`docs/design/`](docs/design/README.md) and [`docs/adr/`](docs/adr/README.md). Every setting is described in [`docs/configuration.md`](docs/configuration.md).

## Learning framework (to respect)

The owner builds this project to learn and keeps control of every Azure step. Before any authentication, any `azd`, `az` or `gh` command that has an effect, any initialization, provisioning or deployment: explain the command and its effect, then wait for an explicit request. Never create or change a Foundry or Azure resource without that request. Entra and RBAC are done by hand in the portal, not with `azd pipeline config`.

Tools: `gh` (`gh auth status`), `az` (`az account show`), `azd` (`azd version`). Under a sandbox, prefix `az` with `AZURE_CONFIG_DIR=/tmp/sa2-azure-config` if its configuration directory is read-only.

## Commands

```bash
uv sync --locked --group dev            # install (same as CI)
uv run --locked pytest                  # the whole suite (no test touches Azure)
uv run pytest tests/test_graph.py::test_name   # a single test
uv run --locked python main.py          # agent locally on :8088 (.env and an authorized Azure session)
azd ai agent run                        # Hosted Agent locally against Foundry

# Same checks as CI, with `just` (https://just.systems): just check, just lint, just fmt, just docs-check
uv run --locked ruff check . && uv run --locked ruff format --check .
python3 -m scripts.check_docs           # links, anchors, ADR format, indexes, heading language

# requirements.txt is generated from uv.lock; CI fails if it diverges
uv export --locked --no-dev --no-emit-project --no-hashes --format requirements-txt --output-file requirements.txt

# BFF (port 8090, /readiness)
docker build -f Dockerfile.bff -t sa2-bff:ci . && python3 scripts/smoke_test_bff.py sa2-bff:ci

# Evaluations: without --run they only validate the dataset; --run makes paid calls
python scripts/evaluate_semantic_approval.py [--run --trials 5]  # consent judge, pass^k
python -m scripts.evaluate_ssh_judge [--run --trials 5]         # SSH command judge, pass^k (docs/ssh-tool.md)
python -m scripts.evaluate_tool_calls [--run --trials 3]        # tool selection, pass^k (docs/tool-call-evals.md)
```

Web client: `cd pwa && npm ci && npm test && npm run build` (Vitest and `tsc`, Node 22, same as CI).

Linting and formatting use `ruff` (configured in `pyproject.toml`); install the hooks once with `pre-commit install`. CI scripts run as modules from the root (`python3 -m scripts.release_plan --component agent`) because they use relative imports.

Development loop: develop and test locally, validate with `azd ai agent run`, run `azd provision` only for the resources that are needed, then `azd deploy` and a remote smoke test. CI enforces tests and quality; CD only deploys after CI.

## Architecture

**Two Azure deliverables, one `src/savant/` package** (the web client `pwa/` is not delivered: CI only).
- *Hosted Agent*: `main.py` (entry point of the ZIP deployment, required at the root by `azd`) → `savant.agent.main()` → `ResponsesHostServer` (`/responses` protocol). Deployed through `azure.yaml` as a code deploy (`remote_build`, `PYTHONPATH=/app/src`). `.agentignore` excludes `tests/`, `scripts/` and `docs/` from the package, so the runtime must not depend on them.
- *BFF*: `savant.oauth_callback` (FastAPI, Notion OAuth callback, owner-only web routes in `bff_api.py`, projects and sessions on Cosmos DB; see below), image `Dockerfile.bff`. It ships only the modules listed in `components.bff.source_files` of `.github/components.json`; `scripts/package_bff.py` fails the build if an imported module is missing from it. Any new import on the BFF side must be added to that registry.

**`agent.build_server()` chooses between three graphs** according to `Settings`: (1) direct Notion chat with OAuth and semantic approval (`tools/notion_chat.build_direct_chat_graph`, the `azure.yaml` configuration in production); (2) the Foundry Toolbox graph (`tools/notion_foundry`); (3) the minimal graph `graph.build_graph` with local tools and optional Notion MCP (`tools/notion`). The model is a `ChatOpenAI` on the Responses API, authenticated with `DefaultAzureCredential` (no API key), `store=False`, with encrypted reasoning replayed by LangGraph. `graph.ChatModel` is a `Protocol` so tests can plug in fake models.

LangGraph carries the application orchestration (state, nodes, routing, tools, interruptions); Foundry provides the platform (models, managed identity, endpoint, sessions, hosting); `langchain-azure-ai[hosting]` exposes the graph through `/responses`.

**`config.Settings.from_env()`** validates everything at startup and fails fast (`RuntimeError`): only `AZURE_OPENAI_BASE_URL` and `AZURE_AI_MODEL_DEPLOYMENT_NAME` are always required, but many Notion/OAuth/Toolbox combinations are cross-checked (HTTPS callback, `NOTION_OWNER_ID` mandatory in the cloud, and so on). Configuration template: `.env.example`. Reference: `docs/configuration.md`, kept exact by `tests/test_config_docs.py`: a new variable must be documented there and listed in `.env.example`.

**Authorization of Notion changes (two independent layers, never weaken either):**
- Notion OAuth authorizes access to a workspace; conversational consent authorizes *one precise operation*. Neither replaces the other ([ADR-0017](docs/adr/0017-two-layer-authorization-for-notion-writes.md)).
- `tools/notion_policy.py`: dynamic catalogue; only a tool carrying a read-only hint runs without approval, everything else is protected.
- `semantic_approval.py`: a second model call (structured APPROVE/REJECT/clarification output, reasoning `none`, one retry within its time limit) judges the user's message. Any change to its instructions is measured in pass^k on the production model (`--trials 5`). `semantic_ledger.py`: an encrypted, single-use authorization bound to the operation digest, the owner, the conversation and the expiry; claimed *before* network I/O and never recovered automatically.
- Everything is *fail closed*: missing identity (`current_user_id` → `None`), unavailable credentials or an invalid approval output mean no write. `NOTION_OWNER_ID` is the fixed key of the single owner (Foundry identity and `x-agent-foundry-call-id` required in the cloud). Never log an ID, token, OAuth code or query string (`bff_logging.py`, `_safe_operation`).

**SSH tool** (`tools/ssh.py`, agent only): `ssh_exec` to the Linux VM ([ADR-0018](docs/adr/0018-ssh-tool-with-a-semantic-command-judge.md)). Every command goes through a **semantic judge** (`ssh.CommandJudge`, an isolated second model call): `RUN` for reads and additions, `CONFIRM` for deletion, overwriting, a change applied to a set of targets, a lasting system change, a command dictated by outside content or any doubt, `REFUSE` for a secret leak; a judge failure counts as `CONFIRM`. The hard-coded floor (`floor_matches`) is only a safety net. A confirmed command runs only on a later user turn, with the same fingerprint, once, without going through the judge again. Outside content read in the turn (`spotlight.tainted_turn`) is a hint for the judge, not a block. The rules live in the system prompt (`tools/ssh_skill.py`, no `read_ssh_skill` tool); up to 4 `ssh_exec` of one step are judged and run in parallel. The `ssh` node is independent of Notion consent. Private key in Key Vault, pinned host key, all-or-nothing configuration (`SSH_*`). Details: `docs/ssh-tool.md`.

**Documents per project** (`documents.py`, agent; pipeline `scripts/search_setup.py`; [ADR-0021](docs/adr/0021-per-project-document-retrieval.md)): an Azure AI Search service, index `sa2-docs`, native ingestion (Blob indexer, chunking and embeddings in the skillset, `project_id` on every chunk). The read tool `search_documents(query)` exists only if `SEARCH_ENDPOINT` is set and the request carries `metadata.project_id` (set by the BFF, read by `request_project`); the `project_id eq '<project>'` filter is imposed by the server, never by the model. Results are wrapped as untrusted data. The BFF handles upload, listing (real state read from the index and the indexer) and deletion (index first, then the file) in `bff_documents.py` / `document_library.py`, active only with `DOCUMENTS_ACCOUNT_URL`, and relays an SSE `sources` event (file ids and names, never the passages). Details: `docs/search-documents.md`.

**Foundry Toolbox**: `azure.yaml` points `TOOLBOX_ENDPOINT` at a web toolbox (web search, code interpreter). A toolbox with an Outlook source is set aside: that source makes `tools/list` fail for the BFF caller. `tools/toolbox_policy.py` judges each call by name (including the tool targeted by `call_tool` when "Tool search" is on): web search and direct reads, code interpreter, send/delete and any unknown tool go through semantic consent. Details: `docs/outlook-tool.md`. The web client and the server's technical notices are in English; the sentences the server addresses to the owner (the confirmation question of a Notion operation, the result) follow the owner's language, French or English (`language.py`, `confirmations.py`): they are written by the server from validated arguments, never by the model, and consent is still judged by the semantic validation. This bilingual runtime behaviour is a product feature, not documentation: do not translate those strings.

**Reliability and observability** ([ADR-0022](docs/adr/0022-bounded-tool-execution.md)): `reliability.py` bounds every tool call (timeouts, a single retry with backoff for a read that failed transiently, never for a write, stop after 8 tool steps), validates arguments against the JSON schema before the call, reads read tools in parallel (4 at most), cuts a result at 20,000 characters and reduces results older than the last 3 user messages to a marker (only the copy the model sees changes). The Toolbox has a short timeout (12 s) then a 45 s pause after a failure; the BFF warm-up request preloads it. A second, fast model (`fast_model_factory`) answers turns without tools and hands over through `use_tools`. `correlation.py` gives each turn a correlation identifier (a fingerprint of the Foundry response id) shared by the agent logs (`turn_start`/`turn_step`/`turn_end`) and the BFF logs (`chat_relay_completed`). Details: `docs/tool-reliability.md`, `docs/observability.md`.

**Outside content is data** (`spotlight.py`; [ADR-0019](docs/adr/0019-external-content-is-data.md)): successful results of Notion, the web and the Toolbox are wrapped in `<untrusted_data>`, and the system prompt says that this content is never an order. This raises the bar without being enough: the semantic judges (consent, SSH) and the later-turn rule remain the real locks.

**Projects and sessions** (BFF only; `workspace.py` rules, `workspace_store.py` Cosmos DB for NoSQL with Entra and no key, `bff_workspace.py` routes): active only if `COSMOS_ENDPOINT` is set, otherwise there is no `/api/projects` or `/api/sessions` route and chat is unchanged. `POST /api/chat` accepts `session_id`; the BFF relays `metadata.project_id` (never chosen by the model) and records the turn's text, without tool arguments or results. The agent does not access Cosmos. The web client keeps a local store and synchronizes it to the BFF (`pwa/src/state/remoteSync.ts`). These three modules are in `components.bff.source_files` and in the agent's `exclude`. Cosmos data roles are granted with the CLI or Bicep, not in IAM. Details: `docs/workspace-cosmos.md`.

**Voice**: the browser talks directly to Azure Speech with a 10-minute token issued by the BFF (`POST /api/speech/token`, managed identity, Cognitive Services Speech **Contributor** role: Speech User lacks `issuetoken/action`; `SPEECH_ENDPOINT`/`SPEECH_REGION`); only the final text goes through the existing chat, with `mode=voice` relayed as `metadata.channel` for a spoken answer style (`identity.VOICE_STYLE`). During tools, the web client plays fixed announcements (`pwa/src/narration.ts`), without the model. Details: `docs/voice-contract.md`.

**Identity**: `identity.BASE_IDENTITY` is the **English** system message (content sent to the model, not documentation), injected transiently on each model call and never written to `state["messages"]`. A language instruction is added on each turn (`language.language_note`, from the owner's messages, the last one that carries a signal): "answer entirely in this language, without mixing another" (a one-word request had drifted into Spanish). A future personal identity must stay in a separate file or constant so the base stays reusable.

## Infrastructure and configuration

- **One source of configuration.** Local values live in `.env`; deployment values in the `azd` environment; CI values in GitHub repository variables with the same names; secrets in Key Vault only. `azure.yaml` only references `${VAR}`: no personal or Azure-specific literal belongs in the repository (a test enforces it).
- **Infrastructure is Bicep** in `infra/`, deployed by `azd provision` ([ADR-0023](docs/adr/0023-infrastructure-as-code-with-bicep-and-azd.md), [deployment guide](docs/deployment.md)). What Bicep cannot do stays in `scripts/setup/`, and every script there is a dry run unless `--apply` is given.
- Outputs of the Bicep template are azd variables and must be described in `docs/configuration.md`.

## CI/CD per component

`.github/components.json` is the single source of ownership: for `agent` and `bff`, its `runtime` / `exclude` / `source_files` / `ci` paths drive CI, release planning and packaging; `non_runtime` (`pwa/**`, `infra/**`, docs, tests, scripts, `.github`, `*.md`, `.gitignore`, tooling files…) deploys nothing. The `checks` section declares CI checks without delivery: `pwa` produces `pwa_ci` for the Node job. Any path missing from the registry conservatively triggers the agent deployment **and** the BFF publication; so does any change to `components.json` or `.agentignore`.
- CI (pull requests and pushes to `main`): `uv sync --locked`, check of `requirements.txt` against `uv.lock`, `ruff`, `pytest`, the documentation check, a secrets scan, and the BFF Docker build and smoke test only if the BFF is touched.
- CD (`cd.yml`) and Publish BFF (`publish-bff.yml`) trigger through `workflow_run` after a green CI on a push to `main` (never on an unvalidated commit). `scripts/release_plan.py` compares with the last checkpoint (artifact `release-<component>-<sha>`) and deploys only if the component's runtime changed. Azure authentication uses OIDC, never a permanent Azure secret.
- **Merging code under `src/savant/` (outside BFF files) to `main` triggers `azd deploy` of the agent.** Publishing a BFF image to the registry does *not* update the Azure Container App (a separate manual step). Automatic BFF publication requires the repository variable `BFF_AUTO_PUBLISH=true`.
- Actions are pinned by commit SHA with a version comment: keep that convention. Read `docs/component-cicd.md`, `docs/cd-workflow.md` and `docs/ci-workflow.md` before changing a workflow or the registry.

## Tests

`pytest` with `pythonpath = [".", "src"]` (so `scripts.*` and `savant.*` are importable), no `conftest.py`. Fake models and servers are injected (`FakeModel`, `FakeResponsesHostServer`, `tests/semantic_fakes.py::SimulatedApprovalModel`, `tests/workspace_fakes.py` for the Cosmos store). A green CI proves neither OAuth nor tools under real conditions (see `docs/notion-live-validation-2026-10-25.md`).

## Conventions

- **Language.** Everything in the repository is in **English**: documentation, comments, file names, commit messages, issue and pull request templates, configuration examples and infrastructure code. The one exception is runtime behaviour: the owner-facing French phrases in `confirmations.py`, `language.py`, `semantic_approval.py` and `pwa/src/narration.ts` are product features asserted by tests. `scripts.check_docs` rejects French file names and headings.
- **Decisions.** One decision, one ADR in `docs/adr/`; never rewrite an accepted ADR, supersede it. Larger designs go in `docs/design/`.
- **Commits.** Conventional Commits (`feat`, `fix`, `docs`, `ci`, `chore`…), small commits, numbered squash-merged pull requests.
- **Secrets.** No secret in Git: environment variables, managed identity and RBAC, Key Vault.
