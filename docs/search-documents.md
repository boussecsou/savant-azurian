# Per-project documents in Azure AI Search

A file dropped into Blob Storage is chunked, vectorized and indexed by Azure AI Search on its own. This page describes the ingestion pipeline, how the agent searches, how the backend uploads, lists and deletes, and the interface. Design context: [SDD-005](design/sdd-005-product-model-memory-and-interface.md) (section 5.3, D5, section 6), [ADR-0021](adr/0021-per-project-document-retrieval.md) and the [search scoping notes](azure-ai-search-project-scoping.md).

## The principle: integrated vectorization

An analogy: a print shop. You hand a manuscript (the PDF) to the front desk (the Blob container). The workshop manager (the **indexer**) takes it, cuts it into sheets (**Text Split**), has each sheet translated into "GPS coordinates of meaning" (an **embedding**, `text-embedding-3-small`) and files each sheet in the big cabinet (the **index**), with the label of its project.

| Object | Name | Role |
| --- | --- | --- |
| Data source | `sa2-docs-blob` | The `documents` container, read with the search service's **managed identity** (no key). |
| Skillset | `sa2-docs-skillset` | Splits (2,000 characters, 300 overlap), then embeds each chunk. The *index projections* write one search document per chunk. |
| Index | `sa2-docs` | One document is one chunk: `chunk`, `chunk_vector`, `title`, `project_id`, `document_id`, `parent_id`. Hybrid search, the semantic ranker, and a **vectorizer** that also vectorizes the question. |
| Indexer | `sa2-docs-indexer` | Runs everything, once at creation and then every 30 minutes. The backend runs it again after each upload. |

**Isolation by project.** The backend gives each blob the metadata `project_id` and `document_id`. They are copied onto every chunk. `project_id` is *filterable* from the first version of the index: an existing field cannot become filterable later. The agent always adds `project_id eq '<project>'` itself, never the model (SDD-005 D6).

**Deletion.** Blob deletion detection does not apply to one-to-many indexing (Microsoft documentation). The backend therefore deletes the chunks first (`document_id eq '<id>'`), then the blob (D8).

**File types (v1).** Text PDF, DOCX, PPTX, TXT, MD. Images and scanned PDFs need OCR (a billed skill): later. Limits on the Basic tier: 16 MB per file, 512,000 extracted characters.

## Why not Foundry's "AI Search" tool?

| Option | Rejected because |
| --- | --- |
| The Azure AI Search tool of the Toolbox | Its filter is fixed for every query: the project of the turn cannot be imposed. |
| Foundry IQ (knowledge base, `knowledge_base_retrieve`) | In preview; the arguments come from the model; one more model call. |
| Foundry IQ, "files" source | In preview, with no isolation by project. |

Ingestion therefore stays **native Azure**. Search is a small tool of our own, with the filter imposed by the server.

## Manual steps (portal, by the owner)

The Bicep template creates the resources and most roles (see the [deployment guide](deployment.md)). On a hand-built setup:

1. **Embedding deployment.** `text-embedding-3-small` (GlobalStandard, 120,000 TPM) is deployed on the Foundry resource. Its endpoint `https://<account>.services.ai.azure.com` is accepted by the skill and the vectorizer (supported domains: `openai.azure.com`, `services.ai.azure.com`, `cognitiveservices.azure.com`).
2. **Container.** On the storage account, create `documents` (private access).
3. **Search service.**
   - *Identity*: enable the **system** managed identity;
   - *Keys*: access control "**Role-based access control**" (or "Both").
4. **Roles** (*Access control (IAM)*):

| Who | Role | On | Why |
| --- | --- | --- | --- |
| The search service identity | Storage Blob Data Reader | the storage account | The indexer reads the files. |
| The search service identity | Cognitive Services OpenAI User | the Foundry resource | Embeddings at indexing and at query time. |
| Your account | Search Service Contributor + Search Index Data Contributor | the search service | Run the setup script and explore the index. |
| The backend identity | Storage Blob Data Contributor, Search Index Data Contributor, Search Service Contributor | storage, search service | Upload, delete chunks, run the indexer. |
| The agent identity | Search Index Data Reader | the search service | Search. |

## Create the pipeline

In `.env` (never committed):

```env
SEARCH_ENDPOINT=https://<service>.search.windows.net
SEARCH_STORAGE_RESOURCE_ID=/subscriptions/<id>/resourceGroups/<group>/providers/Microsoft.Storage/storageAccounts/<name>
SEARCH_EMBEDDING_ENDPOINT=https://<account>.services.ai.azure.com
SEARCH_EMBEDDING_DEPLOYMENT=text-embedding-3-small
```

```bash
uv run --locked python -m scripts.search_setup            # prints the 4 definitions, sends nothing
uv run --locked python -m scripts.search_setup --apply    # creates or updates (PUT, your Entra identity)
```

The script is **idempotent**: running it again updates the same objects. It uses no key and prints only the HTTP status, or the service's error message.

## Check that it works

1. Drop a small PDF by hand into `documents/main/test-doc/` and add two **metadata** entries (in the portal: the blob, then *Metadata*): `project_id = main` and `document_id = test-doc`.
2. On the search service, *Indexers*, `sa2-docs-indexer`, **Run**. Wait for "Success".
3. *Search explorer* on `sa2-docs`, with a query that contains a word from the PDF and the filter `project_id eq 'main'`. Chunks come back, with `title` equal to the file name and `document_id = test-doc`.
4. The same filter with `project_id eq 'other'` returns **nothing**: isolation works.

## Search by the agent

The agent has a read tool `search_documents(query, more_queries?)` (`src/savant/documents.py`). It appears only if `SEARCH_ENDPOINT` is configured **and** the request carries a project.

- **The project comes from the server.** The backend sets `metadata.project_id` from the stored session (Cosmos). `ConversationalResponsesHostServer.build_input` reads it (`request_project`, a plain identifier only) and the tool is built for that turn, bound to that project. The model supplies only `query` (and at most 3 `more_queries`, other angles of the same question, searched **together** in the same call and merged: 8 passages at most, without duplicates, every angle represented: a summary or a list of limits takes one step instead of five, each costing a 5 to 16 s model call). A `project_id` argument added by the model is refused by the schema. Without a project there is no tool (*fail closed*).
- **The query** is hybrid (keywords and vector, the question being vectorized by the index's vectorizer) and re-ranked by the semantic ranker (extractive captions). It returns at most 5 passages of at most 1,200 characters, with `document_id` and the file name.
- **It is a read**: no approval. Several searches in one step run in parallel (4 at most), with the timeouts and the single retry of `reliability.py`. A 429 or a 5xx counts as a transient error.
- **Results are outside content**: they are wrapped in `<untrusted_data>` (`spotlight.py`), like the web and Notion.
- **Log**: `documents_search results=<n> ms=<duration>`, never the question, a title or a passage.
- **Authentication**: the agent's `DefaultAzureCredential`, scope `https://search.azure.com/.default`, no key. Required role for the agent identity: **Search Index Data Reader** on the search service.
- **Configuration**: `SEARCH_ENDPOINT` and `SEARCH_INDEX` (default `sa2-docs`) in `azure.yaml`.

## Upload, list and delete by the backend

Routes reserved to the owner (Easy Auth), mounted only with the workspace (Cosmos) and `DOCUMENTS_ACCOUNT_URL` (`bff_documents.py`, rules in `document_library.py`):

| Route | Effect |
| --- | --- |
| `GET /api/projects/{id}/documents` | Lists with the **real state**: `ready` (the index has chunks of the document), `failed` (indexer error on that file), otherwise `indexing`. |
| `POST /api/projects/{id}/documents?name=<file>` | Body = the raw file (no form). Types: PDF, DOCX, PPTX, TXT, MD; 16 MB at most. Writes `documents/{project}/{document}/{name}` with the metadata `project_id` and `document_id`, then runs the indexer (a 409 "already running" is enough: it will see the file). |
| `DELETE /api/projects/{id}/documents/{doc}` | Deletes the chunks from the index first (filter `project_id` + `document_id`), then the file. |
| `GET /api/projects/{id}/documents/{doc}/file` | Returns the file inline (a PDF opens in the browser), `nosniff`. |

- **The blob is the record**: no extra table. The project must exist in Cosmos; a document of another project answers 404.
- **Deleting a project** also deletes its documents, index first (D8).
- **What is not shown is not searched** (rule D8, corrected on 2026-11-08):
  - *Immediate deletion*: the trash deletes the chunks right away, then the file. The web client first keeps a copy of the file in memory; **Undo** sends it back as a new document (new identifier, re-indexed). Before, deletion waited for the end of the toast (6.5 s): the hidden document stayed searchable, and was never deleted if the tab closed.
  - *Indexer running*: a pass that was already reading the file writes its chunks *after* the deletion. The backend therefore waits for that pass to finish in the background (`settle`, status read every 5 s, 200 s at most), then deletes what no longer has a visible file.
  - *Reconciliation*: every `GET …/documents` reads the index, then the files (in that order, so an upload in progress never looks like an orphan), and deletes the chunks of any document missing from the list. A file dropped by hand (a non-standard identifier such as `test-doc`) is never listed: its chunks go, the file stays. Best effort: a failure does not prevent the list.
  - *Agent-side guard*: `search_documents` ignores any passage whose document does not have a listed identifier (32 hexadecimal characters).
  - Reading and deleting chunks cover more than 1,000 chunks per document.
- **Sources in the chat**: when the agent calls `search_documents`, the SSE relay emits `{"type": "sources", "id": <call>, "sources": [{"documentId", "title"}]}`. Only the identifier and the file name pass, never the text of the passages.
- **Logs**: `document_added size_kb=…`, `documents_failed error_type=…`; never a name or an id.
- **Voice**: during `search_documents`, the web client says "Je regarde ça dans les sources du projet." (then other variants for later calls), without the model (`pwa/src/narration.ts`).

Container App configuration (besides `COSMOS_ENDPOINT`): `DOCUMENTS_ACCOUNT_URL=https://<account>.blob.core.windows.net` and `SEARCH_ENDPOINT=https://<service>.search.windows.net`; optional `DOCUMENTS_CONTAINER` (`documents`), `SEARCH_INDEX` (`sa2-docs`), `SEARCH_INDEXER` (`sa2-docs-indexer`). `SEARCH_ENDPOINT` alone enables nothing on the backend.

Roles of the backend identity: *Storage Blob Data Contributor* on the `documents` container, *Search Index Data Contributor* and *Search Service Contributor* on the search service.

## Interface

`DOCUMENTS_ENABLED` and `ATTACHMENTS_ENABLED` are on (`pwa/src/flags.ts`).

- **Project sources**: the project is the scope of everything below. It is chosen at the top of the rail (a selector: a popover that opens from the button, no more Sessions/Projects tabs), then come its sessions and, at the bottom, the collapsible **Sources · {project}** section. Add with the + button or by drag and drop. Each row shows a badge (PDF, DOC, PPT, MD, TXT), the name (in full on hover), the size and the **real state** (Uploading… during the upload, then Indexing… / Ready / Failed read by the backend, refreshed every 5 s while a document is in progress). Clicking the name opens the file. The trash removes it with a 6.5 s **Undo** toast, after which the real deletion happens (index, then file).
- **Always-visible destination**: a file dropped anywhere on the discussion thread goes to the active project's sources, and a veil says "Add to {project}'s sources" while dragging. The composer's paperclip does the same (its tooltip names the project). There is no persistent chip in the composer any more: a toast says "Added … · indexing…", then "… is ready: Savant can search it" (or the failure), even when the rail is collapsed.
- **Under the answer**: "Sources · N", with one chip per cited document (the `sources` SSE event). A document known to the project opens on click; an unknown document (dropped by hand, for example) is only named.
- **Voice**: "Je regarde ça dans les sources du projet." during the search.
- Refused files (type, size, empty) are announced by a toast with the reason given by the backend.
- Sources are kept for the current page only, like tool steps: they are not saved in Cosmos.

Verified locally against a deployed backend: `GET /api/projects/main/documents` answers 200 through the development proxy. Upload, indexing, opening and deletion still need to be checked in the interface.
