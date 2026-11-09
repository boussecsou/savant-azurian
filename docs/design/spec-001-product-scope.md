# SPEC-001: Savant Azurian product scope

- **Status:** Accepted. A product target, not a statement of what is delivered; see [Delivery status](#delivery-status).
- **Date:** 2026-08-17 (reviewed 2026-11-09)
- **Related:** [SDD-001](sdd-001-mvp-scope-and-use-cases.md), [SDD-002](sdd-002-architecture-and-azure-infrastructure.md)

## 1. Vision

Savant Azurian is a **voice-first personal assistant** that runs on Microsoft Azure. It is built for **one owner**: a single person uses the web client, the backend and the hosted agent.

Core loop: **speech-to-text, then a LangGraph agent, then text-to-speech.** Text input is accepted, and the answer is spoken.

## 2. Interaction model

| Input | Output |
| --- | --- |
| Voice | Voice |
| Text | Voice and text |

- Speech uses Azure Speech Services with neural voices.
- The interactive path recognizes speech continuously, shows partial transcription and triggers the agent on the final utterance ([ADR-0007](../adr/0007-live-stt-with-utterance-final-trigger.md)).
- A request that needs a tool gives a short spoken acknowledgement before a slow tool finishes ([ADR-0008](../adr/0008-main-llm-routes-tools-with-deterministic-feedback.md)).

## 3. Projects and retrieval

- Each **project** has isolated retrieval and memory. The default project is `Main`.
- The owner uploads documents to a project and asks grounded questions about them.
- Stack: Azure Blob Storage and Azure AI Search ([ADR-0021](../adr/0021-per-project-document-retrieval.md)).

## 4. Tools

| Tool | Implementation |
| --- | --- |
| Notion | The official Notion MCP server, with OAuth |
| Linux VM over SSH | `asyncssh`, with the private key in Key Vault |
| Web search and code interpreter | A Foundry Toolbox |
| Document retrieval | Azure AI Search, inside the LangGraph agent |
| Gmail | Planned in the original scope; see the delivery status |

## 5. Architecture, at a high level

```text
Web client  →  Backend (Azure Container Apps)  →  Foundry hosted agent (LangGraph)
```

- **One owner.** Access to the web client and the backend is reserved to that owner. A fixed server-side key identifies them for token storage. A fixed key is a lookup key, not an authentication mechanism.
- Secrets: Azure Key Vault and managed identities.
- State: Cosmos DB.
- Observability: Application Insights and Azure Monitor.

## 6. Out of scope

- Public sign-up and secondary accounts
- Workflow engines such as n8n
- Multi-agent systems
- Fine-tuning
- Third-party text-to-speech

## 7. Acceptance criteria

- A spoken conversation works end to end through the hosted agent.
- A simple request gets a direct spoken answer without a tool round trip.
- A request that needs a tool is routed to the right tool by the main model.
- A noticeable tool operation produces a short spoken acknowledgement first.
- Notion is validated with at least one real end-to-end read: voice request, tool call, workspace result, spoken answer.
- Projects isolate retrieval context.
- The tools work as delivered in the agreed scope.
- All secrets are in Key Vault on the hosted path.
- The backend runs on Container Apps.
- Basic observability is in place.

## Delivery status

Reviewed on 2026-11-09 from the repository's own documentation. It is a map, not a test report; the [live validation reports](../README.md#live-validation-reports) hold the evidence.

| Criterion | Status |
| --- | --- |
| Hosted agent, spoken conversation | Delivered; the voice pipeline was validated end to end on 2026-11-03 |
| Tool routing by the main model, spoken acknowledgements | Delivered |
| Notion read and approved write | Delivered; validated on a real workspace |
| SSH | Delivered, behind a semantic command judge ([ADR-0018](../adr/0018-ssh-tool-with-a-semantic-command-judge.md)) |
| Projects and per-project document retrieval | Delivered ([ADR-0021](../adr/0021-per-project-document-retrieval.md)). Retrieval over past sessions is not |
| Gmail | **Not delivered.** An Outlook source in the Foundry Toolbox was tried and set aside |
| Backend on Container Apps, secrets in Key Vault, observability | Delivered |
| Hosting of the web client | **Not delivered by design:** the web client runs locally ([ADR-0010](../adr/0010-monorepo-local-pwa-and-entra-owner-access.md)) |
