# ADR-0004: Pick the smallest model that completes agentic tasks, and treat it as a reference

- **Status:** Accepted
- **Date:** 2026-08-18 (updated 2026-09-02 and 2026-10-08)
- **Tags:** agent, azure

## Context

The agent needs a reasoning model that handles multi-step tool use. On the Azure for Students subscription ([SPEC-002](../design/spec-002-azure-for-students-constraints.md)) the larger models showed zero quota at the time, so a deployment was refused. A smaller model, `gpt-5-mini`, was deployable with the Global Standard SKU in the chosen region.

The rule behind the choice does not change: use the smallest model that completes the agentic tasks.

## Decision

Use an operational reference model and an explicit upgrade path. The model identifier lives in configuration ([ADR-0006](0006-model-fallback-and-change-control.md)); the agent interface does not change when it moves.

Upgrade path when quota allows, each step justified by a benchmark:

1. `gpt-5-mini`, the starting point.
2. `gpt-5.6-luna`, if it benchmarks at least as well.
3. `gpt-5.6-terra`, only if the previous step fails multi-step tool use.
4. `gpt-5.6-sol`, never the default.

**Do not**

- use a preview model with no quota as a dependency;
- treat a playground "save as agent" as the production hosted agent;
- request a huge throughput quota.

## Consequences

**Positive**

- Cost and latency stay low, and a model swap is a configuration change.

**Negative / risks**

- Reference models change faster than the documents that name them. A production swap needs a new ADR, or an update of this one with status and date, and the same acceptance checks (a speech-to-text smoke test, a listening test, one tool call end to end).

## Updates

- **2026-09-02.** `gpt-5.6-luna` was deployed and validated through Azure OpenAI and Foundry. It replaced `gpt-5-mini` as the development reference. Settings at that point: `reasoning_effort="none"`, `verbosity="low"`, and no `temperature`, because `temperature=0` was rejected by that deployment. This was not yet a final production choice: a later benchmark had to compare cost, latency, tool-use reliability and response quality.
- **2026-10-08.** The runtime moved to the `gpt-6-luna` model through the Responses API with encrypted reasoning replayed by LangGraph. See the [model configuration](../model-gpt-6-luna.md).

## Related

[ADR-0001](0001-non-realtime-voice-pipeline.md), [ADR-0006](0006-model-fallback-and-change-control.md), [SDD-002](../design/sdd-002-architecture-and-azure-infrastructure.md), [SPEC-001](../design/spec-001-product-scope.md)
