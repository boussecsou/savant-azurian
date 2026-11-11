# Notion direct and conversational authorization

> Historical policy note: the proposed interaction update in
> [notion-fluid-interaction.md](notion-fluid-interaction.md) supersedes this
> document's blanket write-confirmation behavior for recognized non-destructive
> Notion operations. The identity, durable-ledger and hosted validation limits
> below remain relevant. Review the new policy and revalidate this work before
> marking it complete.

Updated on 23 October 2026 (semantic guardrail refactor). This document separates implemented behavior, local
simulation, read-only Azure evidence, and validation that still requires an
authorized deployment. It does not declare the validation complete.

## Functional source and scope

The original specification
requires the Hosted Agent and callback to share an encrypted OAuth store, a stable
server-side owner identity, and a real Playground consent/read/approved-write/
refused-write/revocation validation. This implementation prepares those paths for
review; it neither deploys the agent nor changes Azure resources or Notion data.

The existing PKCE flow, callback, Fernet encryption, Blob lease transactions,
Key Vault loading, and Foundry checkpoint saver are reused. Native approval hooks
remain available for the other graph paths. The direct Notion graph uses the new
conversational gate instead.

## Why ordinary conversation turns replace native interrupts here

The locked `langchain-azure-ai` version is 1.2.10. Its `ResponsesHostServer`
re-emits pending LangGraph interrupts when a user sends only text. It resumes
through `function_call_output` or `mcp_approval_response`, not a plain “yes”. Native
interrupts can therefore generate approval UI and do not implement the requested
button-free conversation with this host.

The direct graph instead ends the proposal turn normally. `ConversationalResponsesHostServer`
extracts exactly one current `HumanMessage` from the actual Responses request and
provides its text and host-generated response ID to the entry gate. System,
developer, assistant and tool messages cannot provide authorization. Multi-user-item
requests are deliberately ambiguous. A separate tool-free semantic classifier
interprets only this trusted user turn, the exact operation and the proposal.
Its verdict is an input to the code-enforced authorization gate.

The durable encrypted ledger now records the single currently presented action
and its host-generated response ID. A plain confirmation works with a matching
`previous_response_id` **or** an existing `conversation.id` (string or object).
The SDK resolves the conversation to a user-isolated LangGraph thread; the code
independently binds it permanently to the owner. With no transport linkage, a
stale explicit response reference, a conflicting pending proposal or missing
presentation, the server presents the exact scope again without execution.
The next reply may be ordinary language; technical action IDs are never required.

A confirmation to a terminal action cannot consume it again. The ledger is
consulted even when a checkpoint has lost its pending list. A conversation-only
transport cannot distinguish a newly submitted generic “yes” from a repeated
network request with a newly generated response ID; each is a new trusted turn.
In a serial batch, that turn can authorize only the currently displayed action.
Clients requiring request-level deduplication must retain response linkage.

The host must retain `langgraph_checkpoint` conversation management. Its ordinary
input is then the current request only; history comes from the saver. The client
must retain `previous_response_id` or the conversation ID. A new conversation has
no authority over an action in another thread.

## Authorization state machine

1. A model tool call is checked against the **execution-time** catalog.
2. A potentially mutative call is not executed. Its arguments are validated,
   normalized where applicable, and persisted with its tool/schema fingerprint,
   owner, thread, action ID, expiry and operation digest.
3. The user sees the tool name, exact arguments and full batch scope. The response
   ends; there is no native interrupt or approval button requirement.
4. The next request enters the gate before the general assistant model. The
   dedicated `SemanticApprovalGuardrail` receives the exact recorded operation,
   the confirmation proposal, latest trusted user text and pending count. No
   retrieved Notion content or full conversation history is included.
5. Structured JSON Schema output selects `APPROVE`, `REJECT` or `CLARIFY`. Natural
   consent such as “ui”, “OK”, “Yes, for sure!” or “lance” is interpreted in that
   context. Conditions, altered parameters, quotes, unrelated text or uncertainty
   should return `CLARIFY`. Each batch operation is presented and confirmed
   separately; one reply never approves all.
   Anything but `APPROVE` on the owner's own reply sets the waiting operation (and
   the rest of its batch) aside: it is cancelled in the ledger, nothing runs, and
   the message goes to the model like any other turn, with a one-turn note saying
   the operation was declined or not approved. The owner can refuse, ask a question
   or change the subject without the question coming back; wanting the operation
   again means a new proposal, worded and judged again. A stale response link, an
   untrusted transport, a turn without owner text or a missing judge still keep the
   operation waiting and ask again. There is no approval button: the PWA only sends
   what the owner says or types.
6. Independently of the LLM, the gate validates owner/thread/presentation, refreshes
   OAuth and discovery, verifies the unchanged tool fingerprint and operation
   digest, and atomically claims the action **before** invoking the external tool.
   Claim checks the presentation again transactionally to close concurrent races.
7. Tool results are reported without a generative model continuation or automatic
   retry. Another batch action, if present, requires a fresh user reply.

The grammar and phrase whitelist have been removed. The evaluator cannot execute
tools, change arguments, create permissions, or select an action ID. Invalid
schema output, refusal, incomplete Responses status, tool-call output, parse
errors, timeout and unavailable inference all return `CLARIFY`. No deterministic
fallback approves a write. Semantic misclassification remains a model risk; the
backend scope and single-use controls still apply even to an erroneous APPROVE.
For a changed target/payload, cancel and request a new proposal.

### Evaluator configuration and cost

`SEMANTIC_APPROVAL_MODEL` optionally names an **existing** deployment on the same
Azure OpenAI endpoint; empty means reuse `AZURE_AI_MODEL_DEPLOYMENT_NAME`. No new
model resource or service is provisioned. `SEMANTIC_APPROVAL_TIMEOUT` defaults to
10 seconds and must be >0 and <=30. The tool-free client uses low reasoning,
256 maximum output tokens, no SDK retries and `store=False`. Inputs are bounded
to 24,000 characters; larger scopes remain blocked and need a smaller proposal.
An incompatible model/structured-output capability fails closed, without fallback.
The runtime evaluator model is independent of the Codex development agents.

Ordinary read-only research and preparation remain autonomous. Productivity
instructions encourage relevant initiative; mutative and destructive actions
remain subject to precise consent. No repeated confirmation is requested for an
already claimed exact operation.

### Persistence and replay

`ApprovalLedger` uses a separate namespace in the **existing encrypted OAuth
store**. SQLite transactions provide local serialization; Blob leases provide
cross-instance serialization in Azure. No new storage resource is introduced.
Foundry checkpoints continue to hold conversation and pending action references.

A permanent thread-owner binding, a durable presentation binding, an exact operation digest and a consumed-turn
record protect action scope. Pending requests expire after at most 15 minutes.
The transition `pending → claimed` is durable before network I/O. A claimed,
completed, failed, rejected, expired or uncertain action is never reclaimed.
Replaying an earlier checkpoint cannot authorize that action again.

This is **at-most-once dispatch**, not exactly-once remote completion. A crash
after claim may leave an operation unexecuted or completed with an unknown result.
The graph refuses automatic retries in either case. Inspect the remote resource
or async-task status and obtain fresh consent for any new operation. One invocation
is made by application code; remote/provider behavior is outside this guarantee.
The ledger retains action tombstones and thread bindings; automatic pruning is
intentionally absent because deleting them would weaken replay protection. This
single-owner prototype requires monitoring store growth rather than claiming
unbounded scalability.

## Dynamic tool discovery and policy

The client connects only to `https://mcp.notion.com/mcp`, using the user's bearer
grant outside model arguments and checkpoint state. It explicitly follows every
`tools/list` page, including empty pages with a cursor. Cycles, duplicate names,
and the 250-page ceiling fail closed instead of returning an incomplete catalog.
No caller-bound tools or tokens are cached globally.

`NOTION_TOOL_POLICY=dynamic` exposes the discovered tools without a fixed access
allowlist. Automatic execution requires a literal read-only annotation from the
pinned official server and no known mutative override. Missing, conflicting or
non-boolean annotations require approval. Names/descriptions alone never establish
read safety. Annotations are hints: this policy explicitly trusts the official
Notion service to label reads correctly; it does not extend that trust to arbitrary
MCP servers.

The compatibility mode `NOTION_TOOL_POLICY=allowlist` restricts discovery to the
configured names. `NOTION_READ_TOOL_NAMES` never downgrades a mutative or unknown
tool. `NOTION_WRITE_TOOL_NAMES` can add protection in either mode.

`tools/list` is not proof of entitlement. Notion can expose plan-restricted tools;
their actual errors, access notices and parameter restrictions remain authoritative.
No tool or permission is synthesized, upgraded, or bypassed. The runtime cannot
inventory the real account until the user completes OAuth; only simulated catalogs
were used in local validation for this PR.

Productivity instructions cover focused search, fetching relevant pages and
schemas before edits, reusing IDs, cursors and truncated subtrees, actual-result
reporting, restricted access, and async-task polling without repeating writes.
These are model behavior guidance, not claims of measured live-model competence.
The execution barrier, classification and replay protections are enforced in code.

## Prepared cloud configuration and read-only evidence

Azure CLI reads on 22 October 2026 established:

| Item | Observed / prepared value |
| --- | --- |
| BFF callback | `https://<bff-fqdn>/oauth/notion/callback` |
| Shared store | `https://stsavantazurian2.blob.core.windows.net/notion-oauth/notion-oauth.enc` |
| Key source | `https://kv-savant-azurian-2.vault.azure.net`, secret `notion-oauth-encryption-key` |
| Agent MI selector | `instance_identity.client_id = <agent-identity-client-id>` |
| Existing agent vault role | `Key Vault Secrets User`, vault scope |
| Existing agent storage role | `Storage Blob Data Contributor`, `notion-oauth` container scope |
| BFF key injection | Existing ACA secret reference to that same vault secret |

Azure currently returns equal `client_id` and `principal_id` values for this
agent. The selector was read from the **client field**; equality is not assumed
for other identities. RBAC metadata was inspected; no new assignments were made
and no production secret or credential blob was read as part of this task.

The Responses service is configured with protocol 2.0.0. The locked AgentServer
SDK exposes `get_request_context().user_id` as the value of `x-agent-user-id`;
Microsoft documents that Foundry injects this value after resolving the acting
user. For an Entra-authenticated endpoint, Foundry derives identity from the
validated caller token. The Foundry endpoint documentation says the default
authorization scheme is Entra. An endpoint configured for Header isolation instead
uses custom isolation headers, which the platform does not validate.

`azure.yaml` does not specify the endpoint authorization scheme, and the deployed
endpoint's live setting was not read in this task. The manifest pins
`NOTION_OWNER_ID` to the operator's Entra object ID, but the live
`get_request_context().user_id` value has not been observed. The platform's
cross-agent user key is documented as a stable per-user key; the docs do not prove
that this deployment's value equals the configured Entra object ID. Therefore a
matching owner is **not verified** yet. `NOTION_IDENTITY_DIAGNOSTICS=true` enables
one status-only app log per identity lookup (`MATCH`, `MISMATCH`, `MISSING`) with
no IDs. It is disabled by default, and the existing owner comparison still returns
no user on missing or mismatched identities.
The app also requires both `user_id` and protocol-2.0.0 `call_id` in the hosted
environment; absence of either fails closed before token lookup.

When the endpoint uses Entra authorization, callers cannot choose the acting user
by sending `x-agent-user-id`; the platform resolves that context. In delegated
middle-tier flows, the documented caller header is `x-ms-user-identity` and the
workload needs Foundry's `UserIdentityImpersonation` action. Playground behavior
for this agent and direct runtime reachability were not tested. Consequently,
resistance to client-supplied identity spoofing is **not verified for the deployed
endpoint** until its auth scheme and ingress boundary are inspected. Never select
Header isolation for this owner check. Local direct graph APIs are privileged;
bind local HTTP to loopback or authenticate it.

### Controlled Playground identity check

After a separately authorized temporary deployment, set
`NOTION_IDENTITY_DIAGNOSTICS=true`, invoke the Hosted Agent from the signed-in
Playground owner account, and inspect only the `NOTION_IDENTITY_DIAGNOSTIC` value
in runtime logs. Require `MATCH` before attempting Notion consent. Then use a
second authorized Entra caller that has permission to invoke the agent and try a
read-only request with a forged `x-agent-user-id` equal to the configured owner.
The request must be rejected or log `MISMATCH`/`MISSING`; it must not retrieve the
owner's Notion access token. Do not log request headers, raw IDs, tokens, or OAuth
callback data. Confirm in the Foundry endpoint configuration that authorization
is Entra and inspect whether direct unauthenticated runtime traffic is possible.
Disable the diagnostic setting after capturing the categorical result. Never
test this with Header isolation or a client that can bypass the Foundry endpoint.
`NOTION_OWNER_ID` pins the accepted identity server-side. The manifest uses the
current operator's Entra object ID (`az ad signed-in-user show --query id`),
**not yet proven to equal the Playground header**. A mismatch or missing header
fails closed, before OAuth store access. Do not remove that check to make a test
pass: verify the actual trusted Playground ID during the authorized cloud test,
then adjust the server-side pin through review if required. Neither prompt text,
model arguments, thread IDs nor a shared fallback determine ownership.

The OAuth begin transaction stores this same canonical owner binding; the detached
callback resolves it from single-use state. It does not accept a new owner from
browser parameters. Existing grants created under another owner are not silently
reassigned. Production checkpoint isolation remains enabled.

## Toolbox decision

Read-only inspection of `toolbox-lab-1` found published/default version **1** with
`web_search`, `code_interpreter`, `FoundryMCPServerpreview` and `toolbox_search`.
The MCP catalog exposes `tool_search` and `call_tool`, without read-only annotations.
Catalog search also revealed Foundry operations such as `agent_delete`,
`agent_update`, `model_deployment_delete` and `model_deploy_azure_direct_model`.
None was executed. No Notion server was found in that published configuration.

No explicit approval-policy property appeared in the returned version metadata;
this alone does not establish the absence of all service-side protection. It is
sufficient evidence that classifying the generic dispatcher as “search only”
would be unsafe.

The prepared manifest sets `TOOLBOX_ENDPOINT` empty. The resource and its version
are untouched. Optional coexistence remains in code with duplicate-name rejection
and all Toolbox calls protected, but the general dispatcher requires further scope
review before cloud enablement. Notion validation is isolated from that risk and
from any second consent flow.

## Validation boundaries

Local tests use the real LangGraph and Responses host with simulated models,
OAuth providers and MCP tools. Encrypted SQLite tests recreate the ledger; host
restart tests recreate graph/host/service while retaining the simulated checkpoint
and response-chain stores. A forced stale checkpoint verifies the independent
ledger. These are not process-restart tests of Foundry's production persistence.

The Responses-host integration tests exercise both `previous_response_id` and
`conversation.id`, natural unscoped confirmation, another conversation in the
same owner account, replay, stale response links and duplicate dispatch. The
conversation-only path depends on the platform restoring the same user-isolated
thread for a repeated conversation ID. The deployed Playground request shape and
Foundry checkpoint persistence are **not verified** by ASGI tests; their final
check requires the controlled live protocol steps below.

Previous PR baseline: 224 tests passed on 22 October. The semantic refactor and
identity/continuity checks below are validated on 23 October; historical Azure
metadata reads above were not repeated.
`uv sync --locked --group dev` succeeded and `uv run --locked pytest -q` passed
**243 tests, 23 expected SDK/cache warnings**, with no failing tests. The ordinary
sandbox stalled even for `asyncio.to_thread`; tests were run outside that sandbox
with synthetic transports. Final security review found zero concrete standards
or spec/security defects in the original refactor. `git diff --check` and the
31-case dataset validation also passed. Endpoint/model environment variables
were absent in the isolated worktree, so no live inference was attempted.

The new `NOTION_IDENTITY_DIAGNOSTICS` setting is false by default. Targeted tests
confirmed status-only logs for match/mismatch/missing without printing either
identity, rejection of a hosted user context without the protocol 2.0.0 call ID,
and natural unscoped confirmation with each transport. A second conversation
cannot consume the first conversation's pending action in the local Responses
host. These simulated tests do not establish live endpoint auth, Playground user
identity equality, or Azure checkpoint continuity.

The local deterministic suite includes a synthetic structured model and a real
locked OpenAI SDK with synthetic HTTP responses. These establish application
behavior and wire compatibility, **not semantic model accuracy**. The fixture's
phrase map exists only in tests and is never a production interpreter.

`evals/semantic_approval.jsonl` contains representative bilingual consent,
refusal, typos, quotes, conditions, context changes, batch scope and injection
cases, plus the short spoken answers to a Notion deletion observed in a bug report
("Exactement.", "Oui."). `uv run --locked python scripts/evaluate_semantic_approval.py`
validates only this dataset, without client creation or authentication. After
separately authorizing inference/authentication, add `--run --trials 5` to call the
configured real model, without any tools, graph, OAuth or Notion operations: a
case passes only if all of its trials give the expected decision (pass^k), and
judge failures (rate limit, timeout) are counted apart. A nonzero exit reports
disagreement with expected labels.

Measured on 2026-11-07 against `sa2-gpt-6-luna` : the previous prompt
with `reasoning_effort=low` failed 13 to 15 of the 32 original cases at pass^4,
and answered CLARIFY to a plain "Oui." about one time in two on a deletion; more
reasoning made it worse (`medium`: 5 of 15 deletion cases failed). The current
prompt, which tells the judge to weigh only the owner's intent towards the fully
disclosed proposal, with `reasoning_effort=none`, passed all 44 cases at pass^5
with no judge failure. The judge is retried once inside its timeout so that a 429
shared with the main agent does not look like a hesitation.

The local Docker daemon is unavailable. The real BFF image build/readiness smoke
test must therefore run in GitHub PR CI; the existing workflow is unchanged.

Coverage includes discovery pagination and classification, reads, precise writes,
refusal, ambiguity, changed schemas/arguments, independent batches, replay,
concurrency, owner/thread isolation, injected confirmations, OAuth revocation,
missing tools, uncertain results and credential-safe error handling. Existing
OAuth, callback, model probe and deployment-filter tests remain part of the suite.

No manual deployment, live Notion write, real OAuth consent, or Playground
confirmation was performed. A live cloud run must record all five cases of the original specification,
including stable owner matching and continuity after a real agent restart, before
closing the task. Keep tokens, consent URLs, secrets and raw SDK payloads out of
screenshots and logs. Readiness alone is not that evidence.

### Final real Playground test (requires explicit deployment and write approval)

1. Confirm the deployed endpoint uses Entra authorization, its caller identity is
   the intended single owner, the diagnostic reports `MATCH`, and Playground is
   continuing the same conversation. First validate a read-only Notion Sandbox
   fetch.
2. Select a dedicated disposable Notion Sandbox page and agree on the exact
   before/after title. Ask Savant to make that one change. Confirm the proposal
   shows the right page and exact new title, then reply `ui, lance` in the same
   conversation. Verify the page changed once and the response reports that same
   operation. This step writes real Notion data and must be separately authorized.
3. Retry the same response ID and resend the confirmation. Verify no second
   mutation occurs. Send the old response ID after a newer proposal and verify it
   only re-presents the current scope.
4. Start a second conversation and reply `ui, lance` without a proposal. Verify
   it cannot change the page or consume the first conversation's pending action.
5. For `previous_response_id`, continue the first response chain. For
   `conversation.id`, send both turns using the same conversation ID without a
   previous-response link. Verify the natural confirmation succeeds once in each
   separately prepared sandbox run. A second Entra caller's attempt to continue
   the owner's chain must fail. Avoid sharing any credentials or raw payloads.
6. Restart/recreate the hosted agent between proposal and confirmation, then
   confirm once. Verify Foundry restores the same checkpoint and the durable
   ledger consumes the action exactly once. Finally disable
   `NOTION_IDENTITY_DIAGNOSTICS` and record only categorical evidence.

The approval filter blocks common credential field names and token signatures;
it is defense in depth, not a universal detector for arbitrary secrets pasted
into otherwise ordinary page content. The OAuth credentials handled by this
runtime are never supplied to the model, approval arguments or logging.

## Verified references

- [Notion MCP supported tools](https://developers.notion.com/guides/mcp/mcp-supported-tools)
- [MCP tools and annotations](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [MCP authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Foundry hosted LangGraph agents](https://learn.microsoft.com/en-us/azure/foundry/how-to/develop/langchain-hosted-agents)

SDK behavior was also checked directly in the locked installation:
`hosting/_responses_host.py` (`build_input`, pending-interrupt handling, checkpoint
resolution), `_converters/_hitl.py`, `_foundry_checkpoint_saver.py`, and
`azure.ai.agentserver.responses` request context conversion. Dependency upgrades
must rerun the real-host regression tests before relying on these contracts.

## Development orchestration (23 October)

The existing PR branch was checked out into an isolated worktree; preserved local
work was not staged or committed. Three bounded subagents performed research,
security review and tests. Explicit spawn overrides were used; project/global
Codex config changes were unnecessary. Session `turn_context` records confirmed:

| Role | Actual model | Reasoning |
| --- | --- | --- |
| Principal | `gpt-6.1-sol` | `low` |
| Documentation | `gpt-6-luna` | `high` |
| Security | `gpt-6.1-sol` | `low` |
| Tests | `gpt-6-luna` | `high` |

No stronger model or reasoning escalation was requested. These development
settings do not change the runtime Azure model deployment.

Additional implementation references:
- [LangChain structured output API](https://reference.langchain.com/python/langchain-openai/chat_models/base/ChatOpenAI/with_structured_output)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)
- [OpenAI conversation state](https://developers.openai.com/api/docs/guides/conversation-state)
- [Foundry endpoint authorization schemes](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/configure-agent)
- [Foundry platform request identity](https://learn.microsoft.com/en-us/python/api/azure-ai-agentserver-core/azure.ai.agentserver.core.foundryagentrequestcontext?view=azure-python-preview)
- [Foundry conversation and user isolation](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/multiplex-session-users)
