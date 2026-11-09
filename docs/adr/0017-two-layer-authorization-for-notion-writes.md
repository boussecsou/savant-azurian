# ADR-0017: Authorize Notion changes in two independent layers

- **Status:** Accepted
- **Date:** 2026-11-09 (recorded retrospectively; the decision was taken while the Notion integration was built, in October 2026)
- **Tags:** security, agent

## Context

The agent can change a Notion workspace. A language model that reads untrusted content (pages, web results) and then writes to a workspace is the textbook case where one mistaken or manipulated step does real damage. A single check is not enough, and a check made by the same model that proposes the action is not independent.

Two different questions have to be answered separately:

1. Is the agent allowed to reach this workspace at all?
2. Did the owner approve this precise operation, now?

## Decision drivers

- No write without an explicit, specific, current approval by the owner.
- Fail closed: any doubt means no write.
- Approval must feel like a conversation, not a wall of buttons.
- Approval must be testable and measurable.

## Considered options

| Option | Why it was not chosen |
| --- | --- |
| OAuth alone | It authorizes a workspace, not an operation |
| Native LangGraph interrupts with approval buttons | The locked hosting library re-emits pending interrupts and resumes only through a function-call output or an MCP approval response, not through a plain "yes". It cannot give the requested button-free conversation |
| Let the main model decide whether the owner agreed | It is the component under attack, so its judgement is not an independent check |

## Decision

Use **two independent layers**, and never weaken one on behalf of the other.

**Layer 1: workspace access (OAuth).** Notion's OAuth authorizes access to a workspace. Tokens are encrypted, stored in Blob Storage and keyed by a fixed owner key ([ADR-0009](0009-bff-owns-user-facing-oauth.md)).

**Layer 2: operation consent (conversation).**

- **A catalogue-driven policy.** The tool catalogue is discovered dynamically. Only a tool that carries an explicit read-only hint runs without approval. Everything else is protected.
- **A semantic judge.** A second, isolated model call judges only the owner's message. Its output is structured (approve, reject, or ask for clarification), with reasoning set to none and one retry within its time limit. The judge sees a single trusted user turn taken from the real request; system, developer, assistant and tool messages can never provide authorization.
- **A single-use ledger.** A successful judgement produces an encrypted authorization bound to the digest of the exact operation, the owner, the conversation and an expiry. It is claimed **before** any network I/O and is never recovered automatically. A repeated "yes" cannot consume an action twice.
- **Server-written confirmations.** The question shown to the owner is built by the server from the validated arguments, never by the model.

**Fail closed.** A missing identity, unavailable credentials or an invalid judge output means no write. In the cloud, the fixed owner key and the Foundry call identity are both required.

**Measured, not assumed.** Any change to the judge's instructions is measured in pass^k on the production model (`--trials 5`) against a dataset of cases, before it ships.

## Consequences

**Positive**

- A compromised or confused main model cannot write on its own: it needs a fresh owner message that a separate judge accepts, for that exact operation.
- The judge can be evaluated, tracked and tuned like any other component.

**Negative / risks**

- Every protected write costs an extra model call and an extra turn.
- A finite evaluation set does not prove perfect classification, and the ledger cannot guarantee exactly-once completion at the remote Notion service.
- A conversation-only transport cannot tell a new "yes" from a repeated network request with a new response ID. Clients that need request-level deduplication must keep response linkage.

## Related

[ADR-0009](0009-bff-owns-user-facing-oauth.md), [ADR-0014](0014-approval-stays-conversational.md), [ADR-0018](0018-ssh-tool-with-a-semantic-command-judge.md), [ADR-0019](0019-external-content-is-data.md), [semantic approval design](../notion-semantic-approval.md), [tool-call evaluations](../tool-call-evals.md)
