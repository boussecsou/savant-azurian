# Design record

How Savant Azurian was specified, designed and decided, in three layers that answer three different questions.

| Layer | Answers | Lives in |
| --- | --- | --- |
| **Specifications** (`SPEC-`) | *What must the product be, and under which external constraints?* | this folder |
| **Software design documents** (`SDD-`) | *How is it built?* A coherent body of design, with its trade-offs and what became of it | this folder |
| **Architecture decision records** (`ADR-`) | *Why did we choose X over Y?* One decision each, never rewritten | [`../adr/`](../adr/README.md) |

A specification sets the target, a design document shows the structure that reaches it, and each important decision inside a design document has its own ADR. Design documents are **living**: each ends with a revision history, and says what was delivered and what was not.

## Specifications

| Document | Contents |
| --- | --- |
| [SPEC-001](spec-001-product-scope.md) | Product vision, interaction model, tools, acceptance criteria, delivery status |
| [SPEC-002](spec-002-azure-for-students-constraints.md) | The subscription constraints (budget, regions, quotas) that shaped the decisions |

## Software design documents

| Document | Contents |
| --- | --- |
| [SDD-001](sdd-001-mvp-scope-and-use-cases.md) | MVP scope and use cases, with the delivery status of each |
| [SDD-002](sdd-002-architecture-and-azure-infrastructure.md) | Architecture, Azure resources, security principles, web client and backend |
| [SDD-003](sdd-003-conversational-voice-runtime.md) | Live speech, model-driven tool routing, spoken feedback, and how voice is hosted today |
| [SDD-004](sdd-004-continuous-integration-and-delivery.md) | CI, component-aware delivery, operating notes |
| [SDD-005](sdd-005-product-model-memory-and-interface.md) | Projects and sessions, long-term memory, the new interface, the delivery plan |

## Reading paths

- **In ten minutes:** [SPEC-001](spec-001-product-scope.md), then the diagram of [SDD-002](sdd-002-architecture-and-azure-infrastructure.md).
- **How an agent with real tools stays safe:** [ADR-0017](../adr/0017-two-layer-authorization-for-notion-writes.md), [ADR-0018](../adr/0018-ssh-tool-with-a-semantic-command-judge.md), [ADR-0019](../adr/0019-external-content-is-data.md), [ADR-0020](../adr/0020-keyless-access-with-entra-and-key-vault.md).
- **How the voice works:** [SDD-003](sdd-003-conversational-voice-runtime.md), [ADR-0007](../adr/0007-live-stt-with-utterance-final-trigger.md), [ADR-0015](../adr/0015-browser-voice-interface-contract.md).
- **How it is delivered:** [SDD-004](sdd-004-continuous-integration-and-delivery.md), [component delivery](../component-cicd.md).
- **How to run your own copy:** the [deployment guide](../deployment.md) and the [configuration reference](../configuration.md).

## Conventions

- Documents are in English. Dates are ISO (`YYYY-MM-DD`).
- A document never links to private tooling, tickets or identifiers. Resource names in examples are generic.
- Statuses and delivery notes are dated, and derived from the repository, not from intentions.
- A change of decision means a **new ADR**, not an edit. See [how we use ADRs](../adr/README.md#how-we-use-them).
