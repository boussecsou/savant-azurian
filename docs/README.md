# Documentation

Some notes are still in French and will be translated to English. [`AGENTS.md`](../AGENTS.md) holds the engineering rules.

## Start here

| Document | Contents |
| --- | --- |
| [configuration.md](configuration.md) | Every variable and secret, who reads it, where it is set. A test keeps it exact |

## Design record

How the system was specified, designed and decided. Start with the [design record overview](design/README.md).

| Document | Contents |
| --- | --- |
| [Architecture decision records](adr/README.md) | 22 decisions, one each, with status and tags. The security ones explain how an agent with real tools stays safe |
| [SDD-001](design/sdd-001-mvp-scope-and-use-cases.md) to [SDD-005](design/sdd-005-product-model-memory-and-interface.md) | Scope, architecture, voice runtime, CI/CD, and the product model with the new interface |
| [SPEC-001](design/spec-001-product-scope.md), [SPEC-002](design/spec-002-azure-for-students-constraints.md) | Product scope and the subscription constraints |

## Architecture and security

| Document | Contents |
| --- | --- |
| [notion-semantic-approval.md](notion-semantic-approval.md) | Conversational authorization of Notion mutations |
| [notion-chat-oauth.md](notion-chat-oauth.md) | Direct Notion OAuth in the chat |
| [notion-fluid-interaction.md](notion-fluid-interaction.md) | Concise interaction and deletion approval |
| [ssh-tool.md](ssh-tool.md) | SSH tool and its semantic command judge |
| [toolbox.md](toolbox.md), [outlook-tool.md](outlook-tool.md) | Foundry Toolbox and Outlook |
| [model-gpt-6-luna.md](model-gpt-6-luna.md) | The chat model |

## Features

| Document | Contents |
| --- | --- |
| [voice-contract.md](voice-contract.md) | Voice-first contract and BFF responsibilities |
| [search-documents.md](search-documents.md), [azure-ai-search-project-scoping.md](azure-ai-search-project-scoping.md) | Documents per project in Azure AI Search |
| [workspace-cosmos.md](workspace-cosmos.md) | Projects and sessions in Cosmos DB |
| [bff-pwa-api.md](bff-pwa-api.md) | Owner-only API of the BFF used by the PWA |

## Reliability, evaluation and observability

| Document | Contents |
| --- | --- |
| [tool-reliability.md](tool-reliability.md) | Timeouts, retries, argument validation, confirmations |
| [observability.md](observability.md), [application-insights.md](application-insights.md), [bff-logging-audit.md](bff-logging-audit.md) | Logs, traces, correlation, logging audit |
| [tool-call-evals.md](tool-call-evals.md) | Tool-selection evaluation (pass^k) |

## Delivery (CI/CD)

| Document | Contents |
| --- | --- |
| [ci-workflow.md](ci-workflow.md), [cd-workflow.md](cd-workflow.md) | CI gates and Hosted Agent deployment |
| [component-cicd.md](component-cicd.md) | Agent/BFF ownership and release checkpoints |
| [publish-bff-workflow.md](publish-bff-workflow.md), [bff-release-procedure.md](bff-release-procedure.md) | Publishing the BFF image |

## Live validation reports

Dated evidence of what was actually tested against real services.

- [Notion, 2026-10-25](notion-live-validation-2026-10-25.md)
- [SSH, 2026-11-02](ssh-live-validation-2026-11-02.md)
- [Voice, 2026-11-03](voice-live-validation-2026-11-03.md)

## Research and setup notes

Decisions and walkthroughs written while building the project. They record why a choice was made and may be out of date.

- [research-notion-mcp-architecture.md](research-notion-mcp-architecture.md), [research-bff-key-vault.md](research-bff-key-vault.md), [notion-foundry.md](notion-foundry.md), [notion-local.md](notion-local.md)
