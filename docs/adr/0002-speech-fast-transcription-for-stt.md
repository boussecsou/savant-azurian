# ADR-0002: Use Azure Speech Fast Transcription for speech-to-text

- **Status:** Superseded by [ADR-0007](0007-live-stt-with-utterance-final-trigger.md) as the primary interactive mode
- **Date:** 2026-08-18
- **Tags:** voice, azure

## Context

Utterances come from the web client as short clips, typically 5 to 60 seconds. The project needs French and English, a generally available service on the same Azure bill as the rest, no realtime requirement at this stage, and a small education budget.

## Considered options

| Option | Why it was not chosen as the default |
| --- | --- |
| Azure Speech batch transcription | Queue latency; designed for long files, not for turn-taking |
| `mai-transcribe-1.5` | Better word error rate, but 43 languages, an extra LLM Speech surface and no diarization |
| `gpt-4o-mini-transcribe` | Few regions, a default of 3 requests per minute, a 25 MB limit and a separate Azure OpenAI deployment |
| Whisper | Weaker accuracy and one more resource to run |

## Decision

Use **Azure Speech Fast Transcription** on the shared Speech resource as the default speech-to-text.

- API: Speech REST version `2024-05-15` or later, synchronous or near-synchronous on the utterance file.
- Locales: automatic detection, with an explicit `fr-FR` or `en-US` when known.
- A phrase list of project terms (tool names, project names) if the word error rate is weak.

**Fallback** if the French error rate fails acceptance: `mai-transcribe-1.5` through the LLM Speech API on the same resource.

**Cost and limits.** About US$0.36 per audio hour, so an utterance costs cents. Files up to 500 MB or 5 hours, and 600 requests per minute on S0. None of these limits matter for conversation turns.

## Acceptance

- French and English utterances are transcribed well enough for tool intent.
- The 95th-percentile latency on a 15-second clip is acceptable for interactive use.
- A failure produces a spoken error, never a silent drop.

## Supersession (2026-09-02)

Fast Transcription was validated and stays useful for file-based tests, but it is no longer the primary interactive mode. [ADR-0007](0007-live-stt-with-utterance-final-trigger.md) selects Azure Speech continuous recognition with utterance-final triggering for the conversational voice path.

## Related

[ADR-0001](0001-non-realtime-voice-pipeline.md), [ADR-0005](0005-region-and-shared-speech-resource.md)
