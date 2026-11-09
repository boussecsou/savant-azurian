# ADR-0003: Use Azure Neural HD voices for text-to-speech

- **Status:** Accepted
- **Date:** 2026-08-18
- **Tags:** voice, azure

## Context

Every agent reply is spoken, so the voice has to sound natural, cover French and English, be generally available and live on the same Speech resource as speech-to-text. Volume is that of a conversation, not of an audiobook.

## Considered options

| Option | Why it was not chosen as the default |
| --- | --- |
| Azure Neural (standard) | Cheaper but less expressive. Kept as the cost fallback |
| MAI-Voice-2 | 15 languages, preview or gated voice prompt, fewer regions |
| MAI-Voice-2-Flash | Preview lifecycle risk before the first milestone |
| `gpt-4o-mini-tts` and `tts-hd` | Tiny voice catalogue, region limits and an extra Azure OpenAI surface |

## Decision

Use **Azure Neural HD (DragonHD)** voices on the shared Speech resource.

- English: `en-US-Ava:DragonHDLatestNeural`.
- French: the latest `fr-FR` Neural HD voice if the region offers one, otherwise a generally available `fr-FR` Neural voice.
- Synthesis is request/response, not a batch job. SSML is allowed for rate and pauses only. No custom voice.

**Fallback:** standard Neural voices (about US$16 per million characters) if the HD quota or region is missing.

**Cost.** HD costs about US$22 per million characters, which is negligible at conversation volume. Concurrency is shared with speech-to-text on the same S0 resource.

## Consequences

**Positive**

- A consistent, intelligible voice with a locale switch between French and English.

**Negative / risks**

- A synthesis failure must degrade gracefully: the answer stays on screen and the conversation goes on.

## Implementation note (2026-11)

Synthesis now runs in the browser with the Speech SDK and a short-lived token issued by the backend, so the backend never handles audio. See [ADR-0015](0015-browser-voice-interface-contract.md) and the [voice contract](../voice-contract.md).

## Related

[ADR-0001](0001-non-realtime-voice-pipeline.md), [ADR-0005](0005-region-and-shared-speech-resource.md)
