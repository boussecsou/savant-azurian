# ADR-0006: Keep model identifiers in configuration and control changes

- **Status:** Accepted
- **Date:** 2026-08-18
- **Tags:** voice, agent, azure

## Context

Models retire. Preview SKUs disappear. An education quota is finite. The defaults chosen in [ADR-0002](0002-speech-fast-transcription-for-stt.md), [ADR-0003](0003-azure-neural-hd-voices-for-tts.md) and [ADR-0004](0004-reasoning-model-reference.md) must stay reversible without rewriting the pipeline.

## Decision

The backend and the agent expose **model identifiers as configuration** (application settings, with secrets in Key Vault), never as literals inside LangGraph nodes.

Ordered references and fallbacks:

| Capability | In order |
| --- | --- |
| Interactive speech-to-text | 1. Azure Speech continuous recognition ([ADR-0007](0007-live-stt-with-utterance-final-trigger.md)). 2. Fast Transcription for file-based fallback and diagnostics. 3. Another transcription model only after a measured quality failure |
| Text-to-speech | 1. The Azure Neural voice validated locally. 2. Another Neural or HD voice after listening and latency tests |
| Language model | 1. The current development reference ([ADR-0004](0004-reasoning-model-reference.md)). 2. Another model only after a benchmark or a quota or availability failure. 3. The largest model stays an explicit opt-in, never the default |

A production swap requires:

- a new ADR, or an update of the existing one with status and date;
- the same acceptance checks: a speech-to-text smoke test, a listening test and one tool call end to end.

Preview models are not on the main path.

## Consequences

**Positive**

- Changing a model is a configuration change with a written trail.

**Negative / risks**

- Configuration can drift between environments. This is why every setting is described in the [configuration reference](../configuration.md) and checked by a test.

## Related

[ADR-0002](0002-speech-fast-transcription-for-stt.md), [ADR-0003](0003-azure-neural-hd-voices-for-tts.md), [ADR-0004](0004-reasoning-model-reference.md)
