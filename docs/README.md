# Documentation

Everything is in English. [`AGENTS.md`](../AGENTS.md) holds the engineering rules, and [`status.md`](status.md) says what is delivered and what is validated.

## Start here

| Document | Contents |
| --- | --- |
| [user-guide.md](user-guide.md) | Using the web client: chat, voice, projects, documents, settings |
| [deployment.md](deployment.md) | Stand up your own copy in Azure, step by step, with Bicep and `azd`; roles, troubleshooting, costs, teardown |
| [configuration.md](configuration.md) | Every variable and secret, who reads it, where it is set. A test keeps it exact |
| [status.md](status.md) | What is delivered, what was validated against live services, what is not |

## Design record

How the system was specified, designed and decided. Start with the [design record overview](design/README.md).

| Document | Contents |
| --- | --- |
| [Architecture decision records](adr/README.md) | 23 decisions, one each, with status and tags. The security ones explain how an agent with real tools stays safe |
| [SDD-001](design/sdd-001-mvp-scope-and-use-cases.md) to [SDD-005](design/sdd-005-product-model-memory-and-interface.md) | Scope, architecture, voice runtime, CI/CD, and the product model with the interface |
| [SPEC-001](design/spec-001-product-scope.md), [SPEC-002](design/spec-002-azure-for-students-constraints.md) | Product scope and the subscription constraints |

## Architecture and security

| Document | Contents |
| --- | --- |
| [notion-semantic-approval.md](notion-semantic-approval.md) | Conversational authorization of Notion changes: the judge and the single-use ledger |
| [notion-chat-oauth.md](notion-chat-oauth.md) | Direct Notion OAuth in the chat, the shared key, the identities |
| [notion-fluid-interaction.md](notion-fluid-interaction.md) | Concise interaction and deletion approval |
| [ssh-tool.md](ssh-tool.md) | The SSH tool and its semantic command judge |
| [toolbox.md](toolbox.md), [outlook-tool.md](outlook-tool.md) | The Foundry Toolbox, and the Outlook source that was set aside |
| [model-gpt-6-luna.md](model-gpt-6-luna.md) | The chat model and how it is called |

## Features

| Document | Contents |
| --- | --- |
| [voice-contract.md](voice-contract.md) | The voice contract and the backend's responsibilities |
| [search-documents.md](search-documents.md), [azure-ai-search-project-scoping.md](azure-ai-search-project-scoping.md) | Documents per project in Azure AI Search |
| [workspace-cosmos.md](workspace-cosmos.md) | Projects and sessions in Cosmos DB |
| [bff-pwa-api.md](bff-pwa-api.md) | The owner-only API of the backend used by the web client |

## Reliability, evaluation and observability

| Document | Contents |
| --- | --- |
| [tool-reliability.md](tool-reliability.md) | Timeouts, retries, argument validation, confirmations |
| [observability.md](observability.md), [application-insights.md](application-insights.md), [bff-logging-audit.md](bff-logging-audit.md) | Logs, traces, correlation, the logging audit |
| [tool-call-evals.md](tool-call-evals.md) | Tool-selection evaluation (pass^k) |

## Delivery (CI/CD)

| Document | Contents |
| --- | --- |
| [ci-workflow.md](ci-workflow.md), [cd-workflow.md](cd-workflow.md) | CI gates and agent deployment |
| [component-cicd.md](component-cicd.md) | Agent and backend ownership, release checkpoints |
| [publish-bff-workflow.md](publish-bff-workflow.md), [bff-release-procedure.md](bff-release-procedure.md) | Publishing and rolling out the backend image |

## Live validation reports

Dated evidence of what was actually tested against real services.

- [Notion, 2026-10-25](notion-live-validation-2026-10-25.md)
- [SSH, 2026-11-02](ssh-live-validation-2026-11-02.md)
- [Voice, 2026-11-03](voice-live-validation-2026-11-03.md)

## Research and history

Notes written while building the project. They record why a choice was made and may be out of date.

- [research-notion-mcp-architecture.md](research-notion-mcp-architecture.md), [research-bff-key-vault.md](research-bff-key-vault.md)
- [notion-foundry.md](notion-foundry.md) (the superseded Foundry route), [notion-local.md](notion-local.md) (testing Notion locally)
- [technical-report-2026-11-09.md](technical-report-2026-11-09.md): the audit and plan of the repository preparation
