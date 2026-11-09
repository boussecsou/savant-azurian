# Architecture Decision Records

An ADR records **one** decision: what was chosen, what was rejected, and why, at the time. Together they explain how the system became what it is. Start with the ones tagged **security**: they hold the guarantees that make an agent with real tools safe to run.

## How we use them

- **One decision, one ADR.** A larger body of design goes into a [design document](../design/README.md), which lists its decisions and links to the ADRs.
- **Never rewrite history.** If a decision changes, write a new ADR that supersedes the old one and set the old one's status to *Superseded by*. Small *Update* and *Implementation note* sections record how a decision aged without changing what was decided.
- **Statuses:** *Proposed*, *Accepted*, *Deprecated*, *Superseded*.
- **Format:** [template.md](template.md), a short variant of MADR (context, considered options, decision, consequences).
- **Numbering:** four digits, never reused. ADR-0001 to ADR-0016 keep the numbers they had when they were first written, so older references stay valid. ADR-0017 onwards were recorded retrospectively on 2026-11-09 for decisions already in the code, and say so.

## Index

### Security and authorization

| ADR | Decision | Status |
| --- | --- | --- |
| [0017](0017-two-layer-authorization-for-notion-writes.md) | Authorize Notion changes in two independent layers | Accepted |
| [0018](0018-ssh-tool-with-a-semantic-command-judge.md) | Gate the SSH tool with a semantic command judge | Accepted |
| [0019](0019-external-content-is-data.md) | Treat everything that comes from outside as data | Accepted |
| [0020](0020-keyless-access-with-entra-and-key-vault.md) | Use Entra ID and managed identities everywhere; secrets only in Key Vault | Accepted |
| [0014](0014-approval-stays-conversational.md) | Approval stays conversational: the card only types the owner's answer | Accepted |
| [0011](0011-entra-easy-auth-on-the-bff.md) | Protect the backend with Entra ID Easy Auth and an owner check | Accepted |

### Architecture and platform

| ADR | Decision | Status |
| --- | --- | --- |
| [0009](0009-bff-owns-user-facing-oauth.md) | The Container Apps backend owns user-facing OAuth; tools stay in the hosted agent | Accepted |
| [0010](0010-monorepo-local-pwa-and-entra-owner-access.md) | One repository; web client runs locally; owner access with Entra ID | Accepted |
| [0005](0005-region-and-shared-speech-resource.md) | Deploy everything in Italy North with one shared Speech resource | Accepted |
| [0022](0022-bounded-tool-execution.md) | Bound every tool call: timeouts, validated arguments, limited retries, loop guard | Accepted |

### Agent, models and retrieval

| ADR | Decision | Status |
| --- | --- | --- |
| [0004](0004-reasoning-model-reference.md) | Pick the smallest model that completes agentic tasks; treat it as a reference | Accepted |
| [0006](0006-model-fallback-and-change-control.md) | Keep model identifiers in configuration and control changes | Accepted |
| [0008](0008-main-llm-routes-tools-with-deterministic-feedback.md) | The main model routes tools; the runtime emits deterministic feedback | Accepted |
| [0021](0021-per-project-document-retrieval.md) | Retrieve documents per project, with a server-enforced filter | Accepted |

### Voice

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-non-realtime-voice-pipeline.md) | Start with a non-realtime speech pipeline | Superseded by [0007](0007-live-stt-with-utterance-final-trigger.md) |
| [0002](0002-speech-fast-transcription-for-stt.md) | Use Azure Speech Fast Transcription for speech-to-text | Superseded by [0007](0007-live-stt-with-utterance-final-trigger.md) |
| [0003](0003-azure-neural-hd-voices-for-tts.md) | Use Azure Neural HD voices for text-to-speech | Accepted |
| [0007](0007-live-stt-with-utterance-final-trigger.md) | Recognize speech live; trigger the agent on the final utterance | Accepted |
| [0015](0015-browser-voice-interface-contract.md) | Define the browser voice interface contract | Accepted |

### Web client

| ADR | Decision | Status |
| --- | --- | --- |
| [0012](0012-sessions-and-projects-behind-a-session-store.md) | Keep sessions and projects behind a `SessionStore` interface | Accepted |
| [0013](0013-interface-shows-only-what-exists.md) | The interface shows only what exists | Accepted |
| [0016](0016-single-stylesheet-one-motion-switch-pure-modules.md) | One stylesheet, one motion switch, logic in pure modules | Accepted |
