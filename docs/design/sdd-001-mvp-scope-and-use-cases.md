# SDD-001: MVP scope and use cases

- **Status:** Accepted. Historical scoping document, with the delivery status of each use case added on 2026-11-09.
- **Version:** 2.0 (first written 2026-08-17)
- **Owner:** Ali Boussecsou
- **Related:** [SPEC-001](spec-001-product-scope.md), [SDD-002](sdd-002-architecture-and-azure-infrastructure.md), [SDD-003](sdd-003-conversational-voice-runtime.md)

## 1. Purpose

Define the functional scope and the primary use cases of the first milestone of Savant Azurian, and say honestly what was delivered. The product vision is in [SPEC-001](spec-001-product-scope.md).

The original plan had a hard deadline of 7 September 2026. That date passed without the whole scope being delivered, so this document no longer represents a delivery commitment. It records the scoping, the decisions that moved it, and where each use case ended up.

## 2. Product overview

Savant Azurian is a **voice-first personal assistant** that runs on Microsoft Azure (Foundry and other Azure services). Core loop: **speech-to-text, then a LangGraph agent, then text-to-speech.** Text input is accepted, and the answer is spoken.

The primary voice path later moved to live recognition, final-utterance triggering, model-driven tool selection and immediate spoken feedback during slow tools. See [SDD-003](sdd-003-conversational-voice-runtime.md), [ADR-0007](../adr/0007-live-stt-with-utterance-final-trigger.md) and [ADR-0008](../adr/0008-main-llm-routes-tools-with-deterministic-feedback.md).

## 3. Primary actor

A single owner, by voice or by text. There is no sign-up and there are no secondary accounts.

## 4. Use cases

### UC-001: Voice or text conversation (P0)

The owner speaks or types. The agent processes the request and answers by voice.

*Acceptance:* the speech is captured correctly, the reply is coherent, the reply is spoken with a neural voice, and latency is acceptable for interactive use.

**Status: delivered.** The voice pipeline was validated end to end ([report](../voice-live-validation-2026-11-03.md)).

### UC-002: Project isolation (P0)

The owner works inside a project. Each project has its own retrieval context and conversation memory. The default project is `Main`.

*Acceptance:* projects can be created and switched, documents stay isolated per project, `Main` is always available.

**Status: partly delivered.** Projects and sessions exist ([ADR-0012](../adr/0012-sessions-and-projects-behind-a-session-store.md)), and **document retrieval** is isolated by a server-enforced filter ([ADR-0021](../adr/0021-per-project-document-retrieval.md)). Memory over past sessions is not implemented.

### UC-003: Document retrieval (P0)

The owner uploads documents to a project and asks questions about them.

*Acceptance:* the upload succeeds, relevant context is retrieved, and answers are grounded in the documents.

**Status: delivered** (text-based documents).

### UC-004: Gmail actions (P0)

The agent searches, reads and sends email through the Gmail API, with OAuth credentials in Key Vault.

**Status: not delivered.** An Outlook source in the Foundry Toolbox was tried instead, and set aside because its source made the tool listing fail for the backend caller ([notes](../outlook-tool.md)).

### UC-005: SSH on an Azure VM (P0)

The agent runs commands on a dedicated Azure Linux VM, using an SSH key kept in Key Vault.

*Acceptance:* basic commands run and return output, the key is read securely, and it is useful for monitoring and learning.

**Status: delivered**, behind a semantic command judge ([ADR-0018](../adr/0018-ssh-tool-with-a-semantic-command-judge.md)).

### Added during the work: Notion

The official Notion MCP server was added as a tool, with OAuth and a two-layer authorization model ([ADR-0009](../adr/0009-bff-owns-user-facing-oauth.md), [ADR-0017](../adr/0017-two-layer-authorization-for-notion-writes.md)). It became the first real end-to-end tool.

## 5. Out of scope

- n8n or any external workflow engine
- Custom or self-hosted MCP servers (the official Notion MCP server is explicitly allowed)
- Multi-agent systems
- Fine-tuning
- Third-party text-to-speech
- Public sign-up and secondary accounts

## 6. Original timeline (historical)

| Week | Dates | Focus | Exit criteria |
| --- | --- | --- | --- |
| 1 | 17 to 24 Aug | Foundation | Resource group, Foundry project, Speech, VM, Key Vault, a basic LangGraph skeleton running locally |
| 2 | 25 to 31 Aug | Core pipeline | The full speech loop and projects with retrieval in the cloud |
| 3 | 1 to 7 Sep | Tools and hardening | Gmail and SSH tools live, hosted agent deployed, end-to-end voice tests pass |

The rule was that a complete spoken conversation with at least one real tool call had to work on 7 September. The deadline passed; the plan was then re-scoped around Notion as the first end-to-end tool.

## 7. Success metrics

- An end-to-end voice conversation works in a Foundry hosted agent.
- At least two projects with isolated retrieval.
- Gmail send and an SSH command succeed from the agent.
- All secrets are in Key Vault.
- Basic observability in Application Insights.

## 8. Decisions that changed this document

| Decision | What changed | Record |
| --- | --- | --- |
| Single owner | One owner, a fixed internal key, Gmail and Notion on the owner's accounts, a Fernet key in Key Vault, encrypted tokens in Blob Storage shared by the backend and the agent | [ADR-0009](../adr/0009-bff-owns-user-facing-oauth.md) |
| Backend on Container Apps | Chosen for learning value (Docker, ingress, scaling, managed identity) | [SDD-002](sdd-002-architecture-and-azure-infrastructure.md) |
| Retrieval stack | Blob Storage, Azure AI Search with vector and hybrid search, embeddings from Azure OpenAI, project isolation by filter | [ADR-0021](../adr/0021-per-project-document-retrieval.md) |
| Notion access | Direct OAuth with dynamic client registration and PKCE through the backend; tools run in the hosted agent | [ADR-0009](../adr/0009-bff-owns-user-facing-oauth.md) |
| Static Web Apps dropped | Impossible on the subscription; the web client runs locally (2026-10-30) | [ADR-0010](../adr/0010-monorepo-local-pwa-and-entra-owner-access.md) |

## Revision history

| Date | Change |
| --- | --- |
| 2026-08-17 | First version, with the updated decisions of that day |
| 2026-09-08 | Review: the 7 September deadline noted as passed |
| 2026-10-20 | Notion access architecture revised and made single-owner |
| 2026-10-30 | Web client moved to local execution |
| 2026-11-09 | Rewritten as a single document with delivery status per use case |
