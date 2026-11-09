# ADR-0007: Recognize speech live and trigger the agent on the final utterance

- **Status:** Accepted
- **Date:** 2026-09-02
- **Tags:** voice, agent, azure
- **Supersedes:** [ADR-0002](0002-speech-fast-transcription-for-stt.md) as the primary interactive mode, and the interactive part of [ADR-0001](0001-non-realtime-voice-pipeline.md)

## Context

The first voice pipeline worked end to end, but the browser recorded a whole utterance, built a WAV file, sent it, and only then waited for transcription before the agent started. A measured real turn took about 8.9 s. The product goal is a conversational voice experience with an immediate sense of being listened to and a minimal delay after the user stops speaking.

## Decision

Move the primary voice input from complete-file transcription to **Azure Speech continuous recognition over a progressive audio stream**.

Target behaviour:

- microphone audio is recognized while the user is speaking;
- Azure Speech emits partial recognition events for live captions;
- the **final** utterance event triggers the agent exactly once;
- end-of-utterance detection is measured and tuned;
- the file-based path stays available for tests and as a fallback.

The first target is turn-based, low-latency conversation. Full duplex, barge-in and simultaneous speaking and listening are deferred.

## Consequences

**Positive**

- Recognition overlaps with the user's speech instead of starting after it.
- The interface can show live transcription.

**Negative / risks**

- A persistent audio transport and session management are required.
- Latency must be measured in separate parts: speech duration, endpointing delay, final recognition latency, agent latency and synthesis latency.
- More state and cancellation handling is needed before full duplex.

## Implementation note (2026-11)

Recognition runs in the browser with the Speech SDK and a short-lived token issued by the backend. Only the **final text** reaches the chat endpoint: no audio and no partial text leave the browser. See [ADR-0015](0015-browser-voice-interface-contract.md) and the [voice contract](../voice-contract.md).

## Related

[SDD-003](../design/sdd-003-conversational-voice-runtime.md), [ADR-0001](0001-non-realtime-voice-pipeline.md), [ADR-0002](0002-speech-fast-transcription-for-stt.md), [ADR-0008](0008-main-llm-routes-tools-with-deterministic-feedback.md)
