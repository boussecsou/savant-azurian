# Voice-first contract and BFF responsibilities (task 31)

Extends the text contract (PWA → local Entra proxy → BFF `/api/chat/stream` → Hosted Agent `/responses`) to voice, adding the fewest moving parts.

## Decision

Speech runs **in the browser**, directly against Azure Speech, with a short-lived token minted by the BFF. The agent keeps a text-only contract and never sees audio. No new transport: the existing SSE chat stream carries the voice turn, and the Speech SDK keeps its own connection to Azure Speech. No WebSocket through the BFF, no audio through Azure Container Apps.

```
Browser (PWA, local)                         BFF (Container App)                 Azure
 mic ──► Speech SDK STT ───────────────────────────────────────────────────────► Speech (italynorth)
          final transcript ──► /api/chat/stream ──► relay ──► Hosted Agent /responses
          answer text  ◄────── SSE events ◄──────── relay ◄── answer
 speaker ◄── Speech SDK TTS ◄──────────────────────────────────────────────────── Speech
          token ◄── POST /api/speech/token ◄── managed identity → issueToken ──── AI Services
```

## What the browser sends

| Step | Payload |
| --- | --- |
| Token | `POST /api/speech/token` (no body). The local proxy adds the owner's Entra token. |
| Turn | `POST /api/chat/stream` `{ "message": <final transcript>, "conversation_id": <previous id>, "mode": "voice" }`: a typed message sends `"mode": "text"` (the default), **except while voice mode is on**: chat and voice are then two inputs of the same conversation, so a typed message joins the voice loop (it stops the recognizer, or the answer being read), is sent with `"mode": "voice"` and its answer is read aloud; it shows in the thread as typed. While a turn is running the composer waits (one turn at a time). Only the **final** utterance is sent, never partial results or audio. Language is not sent: the agent answers in the language of the text. |

## What the browser receives

| Source | Content |
| --- | --- |
| `/api/speech/token` | `{ "token", "region", "expires_in" }`, `Cache-Control: no-store`; 404 when voice is not configured, 502/504 on failure. |
| `/api/chat/stream` | Unchanged SSE events: `delta` (answer text), `tool` (name, running/done), `done` (conversation id), `error` (kind). Tool arguments and results never leave the BFF. |

## Responsibilities

| Component | Responsibility |
| --- | --- |
| Browser | Microphone permission; when voice mode starts, a fixed greeting chosen at random from a short list (`narration.ts`, no model; neutral, no "bonjour"/"bonsoir"); STT in the language the owner picked (French by default, English from Settings or the FR/EN button under the orb: a fixed language starts faster and recognizes better than detecting it on every utterance), continuous recognition per utterance that ends after 2 s of silence (`SPEECH_END_SILENCE_MS`, Azure `Speech_SegmentationSilenceTimeoutMs`) so a pause to think does not cut the owner off, with live partial captions under the orb, "Listening" shown only once the microphone stream has started, SDK and token prepared shortly after load; send the final transcript and, at once and without the model, say a short acknowledgment chosen at random from a list that only confirms reception ("D'accord.", "Bien reçu.", "C'est noté.", never twice in a row; never "Je vois" or "Compris", which would claim an understanding the agent has not shown yet) that covers the wait while the agent loads its tools; read the answer aloud as SSML with a matching multilingual neural voice (`fr-FR-VivienneMultilingualNeural` or `en-US-AvaMultilingualNeural`, so an English word inside a French answer is read in English), 15 % faster than the default (`SPEECH_RATE`; the text is XML-escaped; the highlight follows the word-boundary events by word, since offsets may refer to the SSML) (Markdown, code, tables and URLs stay on screen); while the agent works, read short fixed phrases chosen from the tool name only (`narration.ts`), independent of the model: one when a tool starts ("Je cherche ça sur le web.") and one when its result comes back ("Voilà, je regarde les résultats."); a repeated tool gets the next variant; French by default, English when the owner spoke English; at most two phrases wait (the oldest is dropped), 0.6 s apart, and the one being spoken finishes before the answer (5 s at most, `ANSWER_WAIT_MS`: the speaker's end-of-audio event sometimes never comes, so a phrase also ends at its real audio length plus 1.2 s, and a stuck one is cut; a turn once stayed in *Thinking* with its answer on screen and never read); writes, commands and code are announced as *prepared* and their end only says the result is being checked, since they may wait for confirmation; states `listening`, `thinking`, `speaking`; *Mute* (the microphone is released, voice mode stays on) and *Read answers aloud* off (no spoken answer and no announcement); the orb reads a level meter from a second capture of the same microphone (an analyser: no audio leaves the browser and nothing is recorded; if the browser refuses the second capture the orb simply moves on a gentle default), and the answer being read is highlighted word by word from the synthesizer's word-boundary events; the Agent, STT and TTS durations shown under a voice answer are measured in the browser (STT = time the recognizer took to settle after the last partial text); errors told apart: microphone, token, recognition, agent, synthesis (a synthesis failure is not fatal: the answer stays in the thread and voice mode goes on). |
| BFF | Owner check (Easy Auth + owner object id) on every route; mint a 10-minute Speech token with its managed identity (`Cognitive Services Speech Contributor` on the AI Services resource: `Cognitive Services Speech User` lacks `SpeechServices/issuetoken/action` and gets a 401), reuse it for 8 minutes; never log it; relay `mode=voice` as Responses `metadata: {"channel": "voice"}`; keep warm-up and Notion OAuth unchanged. |
| Hosted Agent | Text in, text out, same tools and confirmations. `metadata.channel=voice` adds `identity.VOICE_STYLE` (a voice assistant: punctuate for the ear, a comma or period at every natural breath even if grammar does not need it, since the voice pauses only at punctuation; English words kept in English spelling) to the transient system message (one to three spoken sentences, no Markdown, emoji or URLs); style only, read on every turn. A spoken "yes" reaches the semantic approval like a typed one. |

## Configuration

BFF: `SPEECH_ENDPOINT=https://fp-savant-azurian-2-resource.cognitiveservices.azure.com`, `SPEECH_REGION=italynorth` (both or neither). No key: local auth is disabled on the resource.

## Why not other options

- **Audio through the BFF** (WebSocket): more code, more latency, audio crossing one more service; nothing gained for a single owner.
- **Speech in the agent**: the Responses protocol is text; the agent would need audio plumbing it does not need.
- **Azure Voice Live / realtime models**: a later option for barge-in and lower latency; not needed to prove the pipeline.
