# ADR-0015: Define the browser voice interface contract

- **Status:** Accepted
- **Date:** 2026-11-05
- **Tags:** voice

## Context

The new orb needs live captions, a microphone level, a mute control and the answer highlighted as it is read, without changing the voice contract: **only the final transcript leaves the browser, and no audio or partial text is sent anywhere** (see the [voice contract](../voice-contract.md)).

## Decision

- **Language** is chosen by the owner: French by default, English from the settings or the FR/EN button. There is no "Auto": a fixed recognition language starts faster and recognizes better.
- **Mute** releases the recognizer and keeps voice mode on. The orb shows "Muted", which is a display mode and not a voice state. A muted wait is not counted as silence.
- **Level.** A second capture of the microphone feeds an `AnalyserNode`. Level and spectrum go to **refs**, never to React state, and the orb reads them every frame. If the browser refuses the second capture, the orb moves on a gentle default. Other states use drawn envelopes (thinking, speaking), not measured audio.
- **Captions.** Partial hypotheses replace each other (the last two words are "in progress"). While speaking, the answer is shown three sentences at a time and highlighted from the synthesizer's `wordBoundary` events.
- **Timings.** Speech-to-text is the time the recognizer took to settle after the last partial text. Agent is the chat call. Text-to-speech is the synthesis time. All three are measured in the browser.
- **"Read answers aloud" off** skips the spoken answer **and** the tool announcements.
- A **synthesis failure is not fatal**: the answer stays in the thread and voice mode goes on.

## Consequences

**Positive**

- Voice stays private by construction: the backend sees neither audio nor partial text.

**Negative / risks**

- Two simultaneous microphone captures are untested on iOS and some Android browsers. The fallback is in place.
- The real microphone, token and word-boundary behaviour are not exercised by automated tests, which cannot reach Azure. They are checked by hand against a running development server.

## Related

[ADR-0007](0007-live-stt-with-utterance-final-trigger.md), [ADR-0008](0008-main-llm-routes-tools-with-deterministic-feedback.md), [SDD-003](../design/sdd-003-conversational-voice-runtime.md), [voice contract](../voice-contract.md)
