# Project status

What is delivered, what was validated against real services, and what is not. It is a map, not a test report: the dated [live validation reports](README.md#live-validation-reports) hold the evidence, and a green CI proves neither OAuth nor tools under real conditions.

Last reviewed: 2026-11-11.

## Validated against live services

| Capability | Evidence |
| --- | --- |
| Notion reads, approved writes with independent readback, refusals without side effects, conversation continuity, replay protection | [Notion live validation, 2026-10-25](notion-live-validation-2026-10-25.md) |
| SSH: a read, a refused deletion, an approved deletion, a connection error | [SSH live validation, 2026-11-02](ssh-live-validation-2026-11-02.md) |
| Voice pipeline: spoken question, speech recognition, agent, synthesis (a direct answer and a Notion tool call) | [Voice live validation, 2026-11-03](voice-live-validation-2026-11-03.md) |
| Owner-only access: no token, fake token, forged identity header and owner token all behave as designed | [ADR-0011](adr/0011-entra-easy-auth-on-the-bff.md), [backend API notes](bff-pwa-api.md) |
| Telemetry of the hosted agent reaches Application Insights | [Application Insights](application-insights.md) |
| The consent judge and the command judge, in pass^k on the production model | [SSH tool](ssh-tool.md), [tool-call evaluations](tool-call-evals.md) |

## Built and tested with test doubles, not yet exercised end to end

- **Documents in the interface:** upload, indexing, opening and deletion of project documents. The backend listing was reached through the development proxy; the rest needs a check in the interface ([search documents](search-documents.md#interface)).
- **Notion OAuth revocation and reconnection** under real conditions.
- **The voice interface with a real microphone** in the web client (microphone, Speech token, highlighted words, mute). The pipeline itself is validated; the browser part is listed as unverified in the [voice report](voice-live-validation-2026-11-03.md).
- **Safari, Firefox, screen readers and real phones** for the web client.

## Added during the repository preparation, never run against Azure

| Item | State |
| --- | --- |
| Infrastructure as code (`infra/`) | Written from the Azure and Foundry documentation. **Not yet compiled by a Bicep compiler in the environment where it was written, and never deployed.** [ADR-0023](adr/0023-infrastructure-as-code-with-bicep-and-azd.md) stays *Proposed* until a clean deployment. See [what to verify first](deployment.md#what-to-verify-first) |
| `scripts/setup/` | The dry-run paths were exercised against a fake `azd`. The `--apply` paths have never run |
| Dev container | Not built in the environment where it was written |
| Mock backend (`npm run dev:mock`) | Tested (`pwa/dev/mock-bff.test.ts`) and run locally |
| Release automation, secrets scan, Dependabot | Added with the first public push; their first runs are the validation |

## Designed and not built

- **Gmail.** An Outlook source in the Foundry Toolbox was tried and set aside ([outlook-tool.md](outlook-tool.md)).
- **Retrieval over past sessions** (`recall`, `read_session`). Only retrieval over project documents exists ([ADR-0021](adr/0021-per-project-document-retrieval.md), [SDD-005](design/sdd-005-product-model-memory-and-interface.md#implementation-status)).
- **Canvas and attachments** in the composer: off by design.
- **Azure hosting of the web client:** it runs locally by design ([ADR-0010](adr/0010-monorepo-local-pwa-and-entra-owner-access.md)).

## Known limits worth knowing

- A model's judgement is not a security boundary: the judges, the floor, the later-turn rule and the single-use ledger exist for that reason. A finite evaluation set does not prove perfect classification, and the ledger cannot guarantee exactly-once completion at a remote service.
- The SSH port is open to the Internet in the reference setup, protected by the key, the pinned host key and a dedicated account ([SSH tool, known weaknesses](ssh-tool.md#known-weaknesses)).
- Easy Auth's client secret expires after 365 days and must be renewed.
