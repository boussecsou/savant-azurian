# ADR-0021: Retrieve documents per project, with a server-enforced filter and integrated vectorization

- **Status:** Accepted
- **Date:** 2026-11-09 (recorded retrospectively; the decision was made in November 2026 as the document pipeline was built, following [SDD-005](../design/sdd-005-product-model-memory-and-interface.md))
- **Tags:** rag, azure, security

## Context

Projects are meant to keep their material apart. A question asked in one project must never surface another project's documents, even when the model is manipulated. Documents are added rarely, so a delay of a few minutes before they are searchable is acceptable.

## Decision drivers

- Isolation that does not depend on the model's behaviour.
- The "Azure native" way of doing retrieval, which is also an explicit learning goal.
- Minimal custom code for ingestion.

## Considered options

| Option | Why it was not chosen |
| --- | --- |
| One index per project | More resources to manage for a single owner; the filter is just as strong |
| Cosmos DB vector search | Possible, but the goal is to learn Azure AI Search and to get hybrid search and ready-made document indexers |
| A custom ingestion pipeline pushing chunks | More code to own for a rare operation |

## Decision

- **One index** in Azure AI Search, with a `project_id` field on **every chunk**, filterable from the first version of the index (an existing field cannot be made filterable later).
- **The filter is imposed by the server.** The search tool takes the query only. The project identifier comes from the request metadata set by the backend, never from the model, and the tool adds `project_id eq '<project>'` itself.
- **Integrated vectorization.** An indexer reads a Blob container, a skillset splits each file and embeds the chunks, and a vectorizer in the index embeds the question at query time. The code only drops files into Blob Storage and queries the index.
- **The search tool exists only when a search endpoint is configured and the request carries a project.** Without both, the agent has no document tool.
- **Results are untrusted data**, wrapped like every outside source ([ADR-0019](0019-external-content-is-data.md)).
- **Forgetting is real.** Deleting a document removes it from the index first and then removes the file, so it is not searchable again.
- **Sources, not passages.** The backend relays only the identifier and name of the files used, never the retrieved passages.

## Consequences

**Positive**

- A manipulated model can choose what to look for, never which project to look in.
- Adding a document is a file upload; Azure does the rest.

**Negative / risks**

- Indexing is not instant. The interface shows the real state read from the index and the indexer.
- Only text-based documents are read in this version (PDF, DOCX, PPTX, TXT, MD). Scanned documents need an OCR skill and come later.

## Deferred

[SDD-005](../design/sdd-005-product-model-memory-and-interface.md) also designed retrieval over **past sessions** (an index per turn, `recall` and `read_session` tools). It is **not implemented**; only document retrieval is.

## Related

[SDD-005](../design/sdd-005-product-model-memory-and-interface.md) (D4 to D8), [ADR-0012](0012-sessions-and-projects-behind-a-session-store.md), [ADR-0019](0019-external-content-is-data.md), [search documents](../search-documents.md), [search scoping](../azure-ai-search-project-scoping.md)
