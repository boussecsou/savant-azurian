# ADR-0001: Start with a non-realtime speech-to-text, agent, text-to-speech pipeline

- **Status:** Superseded by [ADR-0007](0007-live-stt-with-utterance-final-trigger.md) for the interactive path
- **Date:** 2026-08-18
- **Tags:** voice, agent, infra

## Context

Savant Azurian is a voice-first assistant whose core loop is speech-to-text, then the LangGraph agent, then text-to-speech (see [SPEC-001](../design/spec-001-product-scope.md)). Realtime speech-to-speech models (Voice Live, `gpt-realtime`, barge-in, voice activity detection) add distributed-systems complexity that the first milestone does not need, and the first milestone has a hard deadline.

## Decision drivers

- Ship a working spoken conversation first.
- Keep each stage independently testable.
- Keep tool calling, project routing and retrieval inside LangGraph, not inside a speech model.

## Decision

Use a **non-realtime request/response pipeline**:

```text
Web client records an utterance
  → backend (Azure Container Apps)
  → speech-to-text on the finished utterance
  → hosted agent (LangGraph, tools, retrieval, memory)
  → text-to-speech
  → backend returns audio to the client
```

- Text input is accepted; output is always spoken.
- No streaming recognition, no interruption handling, no speech-to-speech model in the agent loop.

## Consequences

**Positive**

- Speech-to-text, agent and text-to-speech can be tested separately.
- Explicit routing and tool calling stay in LangGraph.

**Negative / risks**

- End-to-end latency is the sum of the three stages. A measured local turn took about 8.9 s, which is acceptable for a first milestone and not for a conversation.

## Supersession (2026-09-02)

The pipeline validated the first local vertical slice, but it is no longer the target for interactive voice. [ADR-0007](0007-live-stt-with-utterance-final-trigger.md) and [SDD-003](../design/sdd-003-conversational-voice-runtime.md) replace it for the primary conversational path. The file-based request/response mode remains valid as a diagnostic and fallback path.

## Related

[SPEC-001](../design/spec-001-product-scope.md), [SDD-001](../design/sdd-001-mvp-scope-and-use-cases.md), [SDD-002](../design/sdd-002-architecture-and-azure-infrastructure.md), [ADR-0002](0002-speech-fast-transcription-for-stt.md), [ADR-0003](0003-azure-neural-hd-voices-for-tts.md), [ADR-0004](0004-reasoning-model-reference.md)
