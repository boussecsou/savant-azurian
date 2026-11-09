# ADR-0014: Approval stays conversational: the approval card only types the owner's answer

- **Status:** Accepted
- **Date:** 2026-11-05
- **Tags:** security, agent

## Context

The interface prototype's Approve and Reject buttons look like they validate an operation, with a digest and a countdown. In the real system, authorization is a **message from the owner judged by the semantic approval judge**, followed by a single-use, encrypted ledger on the agent side ([ADR-0017](0017-two-layer-authorization-for-notion-writes.md)). The backend relays no operation summary, digest or expiry, and its `consent` flag only means an Outlook sign-in link.

## Decision

- The card titled "Approval needed" has two buttons that **send an ordinary message**: "Yes, go ahead." and "No, do not do it." Nothing else. The card disappears once the owner has answered and never states an outcome. The agent announces the result in the thread.
- It is offered only as a **hint**: the last assistant turn used a write-class tool (a Notion write, `ssh_exec`, the code interpreter, an Outlook send or delete) and ends on a question. Typing the answer works just as well.
- No digest and no countdown are shown while the backend and the agent do not expose them.
- The two authorization layers (OAuth workspace access, per-operation consent) are untouched.

## Consequences

**Positive**

- The interface cannot bypass or fake an approval, because the buttons are only a convenience for typing.

**Negative / risks**

- The hint can be wrong (a card on a turn that was not a request, or none on one that was). The cost is nil: the buttons send an ordinary sentence that the agent judges like any other.
- A real approval card (summary, digest, expiry) needs a backend and agent change, and a new ADR.

## Related

[SDD-005](../design/sdd-005-product-model-memory-and-interface.md) (section 8.3 item 3, scenario S5), [ADR-0008](0008-main-llm-routes-tools-with-deterministic-feedback.md), [ADR-0009](0009-bff-owns-user-facing-oauth.md), [ADR-0017](0017-two-layer-authorization-for-notion-writes.md), [semantic approval design](../notion-semantic-approval.md)
