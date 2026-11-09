# ADR-0022: Bound every tool call: timeouts, validated arguments, limited retries and a loop guard

- **Status:** Accepted
- **Date:** 2026-11-09 (recorded retrospectively; the decision was taken during the reliability work in October 2026)
- **Tags:** agent

## Context

An agent that calls tools can hang, loop, retry a destructive action, flood its own context with a huge result or act on malformed arguments. A voice interface makes every one of these visible as silence.

## Decision

One rule for every tool, implemented in one module and applied in the chat graph.

- **Timeouts at every step.** Model call (90 s by default), the approval and command judges (10 s), loading the Notion catalogue (30 s), one tool call (60 s), SSH (10 s to connect, 30 s per command), and the backend relay. The toolbox has a short timeout (12 s), then a 45 s pause after a failure during which turns answer without it. A warm-up request starts the load ahead of the first turn.
- **Retries by kind of call.** Reads get one retry, only for a transient failure, with backoff and jitter that respects `Retry-After`. **Writes are never retried:** a failure in the middle is reported as an uncertain result and the agent checks the state before trying again.
- **Parallel reads.** Several reads in one step run side by side, four at most, and the results keep the order of the calls. A failed read does not stop the others. Writes go one at a time through the ledger.
- **Arguments are validated** against the tool's JSON schema before the call. A wrong argument is answered at once with the argument concerned, and the tool is not called. A schema that cannot be read never blocks a call.
- **Results are bounded.** A result is cut at 20,000 characters with a note asking for a narrower part. Results older than the last three user messages are replaced by a short marker in what the model sees. Only the model's copy changes: the saved conversation keeps the full result.
- **A loop guard** stops a turn after 8 model steps that asked for tools, and the agent asks the owner how to continue.
- **Every turn has a correlation identifier** (a fingerprint of the Foundry response ID) shared by the agent and the backend logs, so one call can be followed end to end ([observability](../observability.md)).

## Consequences

**Positive**

- No tool call can hang a turn forever, repeat a write silently or exhaust the context.
- A failure produces an honest, short message rather than silence.

**Negative / risks**

- The limits are tuned to one owner's usage and may need adjustment elsewhere. Each is a named constant or setting described in the [tool reliability](../tool-reliability.md) document.

## Related

[ADR-0008](0008-main-llm-routes-tools-with-deterministic-feedback.md), [ADR-0017](0017-two-layer-authorization-for-notion-writes.md), [tool reliability](../tool-reliability.md), [observability](../observability.md)
