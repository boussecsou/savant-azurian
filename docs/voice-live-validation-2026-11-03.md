# Voice pipeline validation — 2026-11-03

Agent: deployed `sa2-agent` (main at the time of the test). Speech: AI Services resource `fp-savant-azurian-2-resource`, region italynorth, Entra-issued token (no key). Tool: `scripts/voice_roundtrip.py` (TTS of the question → STT → agent `/responses` → TTS of the answer), run with the owner's Azure session.

| Turn | Heard (STT) | Agent answer | STT | Agent | TTS |
| --- | --- | --- | --- | --- | --- |
| Direct answer | « Bonjour savan en une phrase, qui es-tu ? » | « Je suis Savant, un agent d'IA qui vous aide à trouver des informations, organiser votre travail et accomplir des tâches concrètes. » | 1.1 s | 28.0 s | 1.2 s |
| Notion tool call | « Combien de taches du projet SAVANT azurian 2 sont en cours dans notion ? » | « Il y a **1 tâche en cours** dans le projet **Savant Azurian 2** sur Notion. » (correct) | 1.3 s | 71.8 s | 1.1 s |

Both turns produced `question.wav` and `answer.wav`. Earlier checks on the same resource: `issueToken` with an Entra token answered 200; 556 neural voices listed in italynorth, including `fr-FR-DeniseNeural` and `en-US-AvaMultilingualNeural`.

## Still to prove in the PWA (needs the owner's microphone)

After the BFF image with `/api/speech/token` is deployed, the role assigned and the two `SPEECH_*` variables set:

1. Tap the orb, say « Quelle est la météo à Rome ? » → web search step, spoken answer.
2. Say « Liste mes tâches SA2 en cours » → Notion step, spoken answer.
3. Ask a Notion write, answer « non » aloud → nothing written; ask again, answer « oui » → written once.
4. Deny the microphone → "Microphone unavailable"; stop the network → agent error shown, nothing spoken.
5. Find the turns in Application Insights with the correlation id (`docs/observability.md`).
