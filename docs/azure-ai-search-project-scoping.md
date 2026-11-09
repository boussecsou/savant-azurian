# Azure AI Search: how `project_id`, the index and queries fit together

Reference for the RAG task ("Blob Storage → embeddings → AI Search", Notion TO-DO, phase C). It explains the
vocabulary, how a document becomes searchable chunks, how a query is built, and how the agent keeps every
search inside **one project**. Nothing here is deployed yet: the code samples are sketches, not tested code.

Facts marked *(doc)* come from Microsoft Learn (links at the end). Everything else is a design decision for
Savant and can change.

---

## 1. The idea in one page

- Savant has **projects**. `Main` always exists. Each chat **session** belongs to one project
  (`docs/workspace-cosmos.md`).
- Documents will be added *per project*. When the owner asks something inside project A, the agent must
  retrieve passages **only from A's documents**, and tell the owner where each passage came from.
- Azure AI Search stores **chunks** (small pieces of documents) in an **index**. Every chunk carries a
  `project_id` field. Every query carries a **filter** `project_id eq '<id>'`.
- The filter is added by **our code**, from the session's project. The model never writes it and never sees
  a parameter that could change it.

```text
PWA ── session_id ──▶ BFF ── reads session (Cosmos) ──▶ projectId
                       │
                       └─ metadata.project_id ─▶ Agent ─▶ search tool(query only)
                                                              │  adds: filter = project_id eq '<id>'
                                                              ▼
                                                      Azure AI Search index
                                                      (chunks of ALL projects, each tagged)
```

**Analogy.** The index is one big library. Every book (chunk) has a coloured sticker (`project_id`). The
librarian (our tool) is told by the front desk (the BFF) which colour the visitor may read, and only ever
fetches books of that colour. The visitor (the model) can ask *what* to look for, never *which colour*.

---

## 2. Vocabulary

| Term | Meaning |
| --- | --- |
| **Search service** | The Azure resource you pay for. Holds indexes. Capacity = replicas × partitions = search units (SU). |
| **Index** | An independent searchable structure with a **schema**. Queries target exactly one index. |
| **Document** | One record in an index. In a RAG index, one document = one **chunk**. |
| **Field** | A named, typed column of a document. Behaviour is set by attributes (below). |
| **Chunk** | A piece of a source file (a few hundred words) sized to fit an embedding model and a prompt. |
| **Parent** | The source file a chunk came from. Its key is stored on each chunk as `parent_id`. |
| **Embedding / vector** | A list of numbers (e.g. 1536 floats) that represents the meaning of a text. Similar meaning → close vectors. |
| **HNSW** | *Hierarchical Navigable Small World*: the approximate nearest-neighbour (ANN) graph used to find close vectors fast. |
| **`k`** | How many nearest vectors a vector query asks for. |
| **Filter** | An exact-match OData boolean expression that includes or excludes documents (`project_id eq 'main'`). No scoring. |
| **Keyword (full-text) search** | Lexical search (BM25) over `searchable` text fields. Good for names, codes, exact terms. |
| **Vector search** | Nearest-neighbour search over a vector field. Good for meaning ("same idea, different words"). |
| **Hybrid search** | Keyword + vector in **one request**, run in parallel and merged with **RRF** (*Reciprocal Rank Fusion*). |
| **Semantic ranker** | Optional re-ranking of the top results by a language model, plus captions. Needs a *semantic configuration* on the index. |
| **Indexer** | A robot that pulls from a data source (e.g. Blob Storage) and fills an index. |
| **Skillset** | The indexer's pipeline steps: split text, call an embedding model, and so on. |
| **Index projection** | Skillset setting that turns one parent document into many chunk documents ("one-to-many indexing"). |
| **Knowledge source / knowledge base** | Foundry IQ / agentic retrieval objects that wrap an index and orchestrate multi-query retrieval. See §10. |

### Field attributes you must choose up front

| Attribute | Means | Used for |
| --- | --- | --- |
| `key` | Unique id of the document. | Required, exactly one, `Edm.String`. |
| `searchable` | Included in full-text (or vector) search. | `chunk`, `title`, `chunk_vector`. |
| `filterable` | Can appear in a `$filter`. | `project_id`, `parent_id`, `source`. |
| `retrievable` | Can be returned in results. | Anything the agent must cite. |
| `sortable` / `facetable` | Ordering / counting by value. | Not needed here: keep `false` to save space. |

**You cannot make an existing field filterable** *(doc)*: you add a new field or rebuild the index. So
`project_id` must be `filterable` from the first version of the index. Filterable fields also grow the
index, so leave the flag off for fields that never appear in a filter.

---

## 3. Where `project_id` comes from in Savant

| Step | Where | What happens |
| --- | --- | --- |
| 1 | PWA | The owner works in a session; the session belongs to a project. |
| 2 | BFF (`bff_api._agent_payload`) | For a chat with `session_id`, the BFF reads the stored session and sets `metadata.project_id`. The code comment is explicit: *the model never chooses the project* (SDD-005 D6). |
| 3 | Agent | **Not wired yet.** Today only `metadata.channel` is mapped into the graph state (`semantic_approval.request_channel` → `state["channel"]`). A `project_id` state key must be added the same way (new work for the RAG task). |
| 4 | Search tool | Reads `project_id` from the graph state and builds the filter. If it is missing, the tool refuses (fail closed, like every other gate in this repo). |

Project ids are validated by `workspace.ID_PATTERN = [A-Za-z0-9_.:-]{1,64}` (`main` or a UUID hex). They
contain no quote character, which matters for OData escaping (§8).

---

## 4. One index or one index per project?

Azure documents four multi-tenant patterns *(doc)*: index per tenant, service per tenant, a hybrid, and
**one shared index with a tenant identifier field and a filter**. Savant has *one owner* and several
*projects*, so "tenant" here means "project", and the stake is correct scoping rather than defence against
hostile tenants.

| | Shared index + `project_id` filter (recommended) | One index per project |
| --- | --- | --- |
| Index count | 1, whatever the number of projects | N projects → N indexes (Free: 3, Basic: 15, Standard S1: 50) |
| Creating a project | Nothing to provision | Create an index + indexer objects |
| Deleting a project | Delete its chunks by filter | Delete the index |
| Isolation strength | **Only as strong as the filter code.** Forget the filter once → cross-project leak. | Index name chosen by code; stronger, but the doc stresses the index name is *not* an authorization boundary by itself |
| Relevance scoring | Statistics are shared: other projects' documents influence BM25 scores *(doc)* | Per-project statistics |
| Fits the limits | Yes | Capped by the tier's index limit |

Recommendation: **one shared index**, and a single code path that builds the filter (§8), covered by a test
that fails if a query is ever sent without it.

---

## 5. Index schema (proposal)

One document per chunk; parent fields repeat on every chunk (the pattern Azure recommends for RAG, because
classic search has no joins) *(doc)*.

| Field | Type | Attributes | Why |
| --- | --- | --- | --- |
| `chunk_id` | `Edm.String` | `key`, `retrievable`, analyzer `keyword` | Unique id of the chunk. |
| `parent_id` | `Edm.String` | `filterable`, `retrievable` | Id of the source file. Required to be filterable by index projections; lets us delete or refresh all chunks of one file. |
| `project_id` | `Edm.String` | `filterable`, `retrievable` | **The scoping field.** Exact match only. |
| `title` | `Edm.String` | `searchable`, `retrievable` | File name or heading, shown as the source. |
| `source` | `Edm.String` | `filterable`, `retrievable` | Blob path / URL, for citations. |
| `chunk` | `Edm.String` | `searchable`, `retrievable` | The text returned to the agent. |
| `chunk_vector` | `Collection(Edm.Single)` | `searchable`, `dimensions` = embedding size, vector profile | Embedding of `chunk`. Not filterable (vector fields cannot be filtered). |

```json
{
  "name": "sa2-chunks",
  "fields": [
    {"name": "chunk_id",   "type": "Edm.String", "key": true, "analyzer": "keyword"},
    {"name": "parent_id",  "type": "Edm.String", "filterable": true},
    {"name": "project_id", "type": "Edm.String", "filterable": true},
    {"name": "title",      "type": "Edm.String", "searchable": true},
    {"name": "source",     "type": "Edm.String", "filterable": true},
    {"name": "chunk",      "type": "Edm.String", "searchable": true},
    {"name": "chunk_vector", "type": "Collection(Edm.Single)", "searchable": true,
     "dimensions": 1536, "vectorSearchProfile": "hnsw-default"}
  ],
  "vectorSearch": {
    "algorithms": [{"name": "hnsw-config", "kind": "hnsw"}],
    "profiles":   [{"name": "hnsw-default", "algorithm": "hnsw-config"}]
  }
}
```

`1536` is a placeholder: it must equal the output size of the embedding model we choose, and every chunk and
every query must use that **same** model. Changing the model later means re-embedding everything.

Text filters are **case-sensitive** and need an exact match *(doc)*. Our ids are lowercase, so that is fine;
if ids ever mix cases, define a normalizer on the field.

---

## 6. Ingestion: how each chunk gets its `project_id`

Two routes, and the choice drives cost and tier (see the tier notes in §10).

### A. Push from our code (simple, full control)

1. A document is added to project P (path to be defined in the task).
2. Our code splits it into chunks, calls the embedding model, and uploads documents
   `{chunk_id, parent_id, project_id: P, title, source, chunk, chunk_vector}`.
3. Because *we* write the document, `project_id` comes straight from the authenticated session, never from
   the file contents.

### B. Indexer from Blob Storage (managed pipeline)

1. Raw files live in Blob Storage, for example under `<container>/<project_id>/<file>`.
2. An **indexer** reads the container; a **skillset** splits text (Text Split skill) and embeds it
   (Azure OpenAI Embedding skill).
3. An **index projection** produces the chunk documents and copies parent values onto each chunk, including
   `project_id`, which must be derived from blob metadata or the path.
4. Deleting a source file removes its chunks only if the data source has a deletion-detection policy;
   otherwise delete the chunks manually *(doc)*.

Route B is where a mistake is easiest to make silently (a wrong path-to-`project_id` mapping tags a chunk with
the wrong project). Whatever the route, `project_id` must come from a **trusted source** (the session or a
path that only our code writes), and ingestion needs the same test as queries.

---

## 7. Anatomy of a query

All three query styles are one `POST /indexes/{index}/docs/search` request; they differ in which parameters
are present.

| Parameter | Role |
| --- | --- |
| `search` | Keyword query text. `"*"` means "match everything" (used with a filter alone). |
| `filter` | OData filter applied to `filterable` non-vector fields. **One filter per request**, but it can have many clauses. |
| `select` | Which fields to return (keep the vector field out: it is large). |
| `top` | How many documents to return. |
| `vectorQueries[]` | One or more vector queries: `kind`, the query `vector` (we embed the question), `fields` (which vector field), `k`. |
| `vectorFilterMode` | When the filter applies to a vector query: `preFilter`, `postFilter`, or `strictPostFilter` (preview). |
| `queryType` + `semanticConfiguration` | Turns on the semantic ranker. |

### The three styles, all scoped to a project

```json
// 1. Keyword only
{ "search": "refund policy", "filter": "project_id eq 'main'",
  "select": "chunk_id,title,source,chunk", "top": 8 }

// 2. Vector only (the question has been embedded by us)
{ "filter": "project_id eq 'main'", "vectorFilterMode": "preFilter",
  "select": "chunk_id,title,source,chunk", "top": 8,
  "vectorQueries": [{ "kind": "vector", "vector": [0.01, -0.02, "..."],
                      "fields": "chunk_vector", "k": 50 }] }

// 3. Hybrid (keyword + vector in one request, merged by RRF)
{ "search": "refund policy", "filter": "project_id eq 'main'", "vectorFilterMode": "preFilter",
  "select": "chunk_id,title,source,chunk", "top": 8,
  "vectorQueries": [{ "kind": "vector", "vector": [0.01, -0.02, "..."],
                      "fields": "chunk_vector", "k": 50 }] }
```

Why hybrid: vector search finds conceptually similar text even with no shared words, keyword search wins on
exact terms such as names, codes and dates; together they cover both *(doc)*. RRF scores look small
(for example 0.03) by design: compare ranks, not magnitudes.

### How the filter meets the vector search

Vector fields cannot be filtered, but the filter on `project_id` narrows which documents the vector search
considers *(doc)*:

| Mode | When the filter runs | Effect |
| --- | --- | --- |
| `preFilter` (**recommended, default on indexes created after about Oct 2023**) | *During* HNSW traversal | Returns `k` results if they exist; best recall; more CPU when the filter is very selective |
| `postFilter` | After each shard's nearest-neighbour search | Faster, but may return fewer than `k` results (false negatives) |
| `strictPostFilter` (preview) | After the global top-`k` | Most false negatives; can return nothing |

A key point for isolation: **all three modes apply the filter, so no mode returns another project's chunks.**
The modes trade *completeness* of results, not *safety*. We still use `preFilter`: a project with few
documents is a highly selective filter, exactly the case where post-filtering can silently return too little.
For very small projects, `exhaustive: true` on the vector query is an option *(doc)*.

---

## 8. Enforcing the filter (the rule that matters)

> **The model chooses the query text. Code chooses the project.**

Design rules for the search tool:

1. **The tool's schema exposes `query` only.** There is no `project_id`, `filter` or `index` argument for the
   model to fill in or be tricked into changing.
2. **`project_id` is read from graph state** (set from `metadata.project_id`), then checked against
   `workspace.ID_PATTERN` before use.
3. **Fail closed.** No project in state → no search, plain error to the model (same style as
   `current_user_id` → `None` elsewhere in the repo).
4. **One function builds the filter**, and it is the only place a search request is created. A test asserts
   that no request leaves without a `project_id` clause.
5. **Escape values in OData.** A single quote inside a string literal is written twice (`''`). Our ids cannot
   contain quotes, but validating first and escaping anyway keeps the rule safe if the id format changes.
6. **Do not rely on the model to filter.** The agentic-retrieval docs say it directly: query hints and
   model-generated filters are *best effort*, and "for required constraints, such as authorization
   boundaries, use document-level access control or a deterministic filter instead" *(doc)*. A
   `project_id` clause is exactly such a deterministic filter.

Sketch (Python, `azure-search-documents`; untested, check names against the installed version):

```python
from azure.identity.aio import DefaultAzureCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.models import VectorizedQuery

async def search_project(client: SearchClient, project_id: str, query: str, vector: list[float]):
    if not ID_RE.fullmatch(project_id or ""):          # fail closed
        raise PermissionError("no project in scope")
    flt = f"project_id eq '{project_id.replace(chr(39), chr(39) * 2)}'"
    results = await client.search(
        search_text=query,                              # keyword leg
        vector_queries=[VectorizedQuery(vector=vector, k_nearest_neighbors=50, fields="chunk_vector")],
        vector_filter_mode="preFilter",
        filter=flt,                                     # server-side, never from the model
        select=["chunk_id", "title", "source", "chunk"],
        top=8,
    )
    return [r async for r in results]
```

What is returned to the model must include `title` / `source` so the agent can cite sources (a requirement of
the task), and, like every other outside content, should be marked as data (`spotlight.wrap`): a document is
untrusted text and may contain instructions.

---

## 9. Identity and permissions (keyless, like the rest of the project)

Roles (assigned by hand in the Portal, per the project's learning rule) *(doc)*:

| Principal | Role | Why |
| --- | --- | --- |
| You (admin, while building) | **Search Service Contributor** + **Search Index Data Contributor** | Create the index; upload test documents |
| Agent identity (query only) | **Search Index Data Reader** | `search`, `lookup`, and `retrieve` on knowledge bases; no writes |
| Whatever ingests documents (BFF or a job) | **Search Index Data Contributor** | Upload and delete chunks |
| Search service's own managed identity (route B only) | **Storage Blob Data Reader** on the storage account | Lets the indexer read blobs without a key |

Two cautions:

- **A role on an index is not tenant isolation.** The index name in a request is not an authorization
  boundary; roles are granted per service or per index, never per `project_id` value. The `project_id`
  filter is what separates projects *inside* the index, which is why §8 is strict about it.
- **No API keys.** Keys grant service-level access and are not tenant-aware. The Entra-only setup also
  means turning key authentication off on the service (`disableLocalAuth`), as a deliberate later step.

---

## 10. Tier consequences and the Foundry IQ alternative

**Tier.** The doc page for keyless connections lists as a prerequisite that the service be on a **billable
tier (Basic or higher)** *(doc)*. Free also lacks managed-identity outbound access for indexers, IP firewall
and Private Link. So the Entra-only design in §9 effectively needs **Basic**, not Free. Free remains fine
for a throw-away experiment with a key. You cannot change Free to Basic in place (recreate the service).

**Foundry IQ / agentic retrieval.** A *knowledge base* wraps one or more *knowledge sources*; a *search
index knowledge source* wraps an index like the one in §5. At query time, a retrieve request can carry a
per-source `filterAddOn` OData expression, which is combined (`AND`) with any stored `baseFilter` *(doc)*:

```json
"knowledgeSourceParams": [{
  "knowledgeSourceName": "sa2-chunks-ks",
  "kind": "searchIndex",
  "filterAddOn": "project_id eq 'main'"
}]
```

The same §8 rules apply: the filter is set by code, not by the model. Things still to verify before choosing
this route: API stability (the GA version `2026-04-01` supports only minimal, extractive retrieval; query
planning and reasoning effort are in the preview version), compatibility of our model deployment with query
planning (supported: `gpt-4o`, `gpt-4.1`, `gpt-5` series), and the extra token cost.

---

## 11. Proof checklist (from the Notion task)

| Check | How |
| --- | --- |
| A document added to `Main` is found by Savant | Upload → ingest → ask in a `Main` session → sourced passage returned |
| Retrieval is filtered by `project_id` | **Negative test**: same question from a session of another project returns no chunk of `Main` |
| Sources are identifiable | Each returned passage carries `title` and `source`; the answer cites them |
| Filter cannot be skipped | Unit test: every search request built by the tool contains a `project_id` clause; missing state → refusal |
| Cross-project deletion | Deleting a project removes its chunks (filter delete) and nothing else |

---

## 12. Open questions

1. Embedding model and dimensions (drives `dimensions` and the vector quota; `vector quota` is per partition).
2. Ingestion route A (push) or B (indexer); where the owner adds documents (PWA upload → BFF → Blob).
3. Where `project_id` enters the graph state, and whether the Hosted Agent host forwards arbitrary
   `metadata` keys the way it does `channel`.
4. Which service tier and region (Italy North is listed with higher storage limits *(doc)*).
5. Classic search tool (our code builds the query) vs knowledge base (`filterAddOn`).
6. What happens to a project's chunks when its project is deleted (workspace rules delete sessions and
   messages; the search side needs the same rule).

---

## Sources

- [Multitenant SaaS patterns and Azure AI Search](https://learn.microsoft.com/azure/search/search-modeling-multitenant-saas-applications)
- [Filters for keyword search](https://learn.microsoft.com/azure/search/search-filters)
- [Add a filter to a vector query](https://learn.microsoft.com/azure/search/vector-search-filters)
- [Hybrid search](https://learn.microsoft.com/azure/search/hybrid-search-overview) and [hybrid query](https://learn.microsoft.com/azure/search/hybrid-search-how-to-query)
- [Index projections (parent-child indexing)](https://learn.microsoft.com/azure/search/search-how-to-define-index-projections)
- [Create an index for agentic retrieval](https://learn.microsoft.com/azure/search/agentic-retrieval-how-to-create-index)
- [Retrieve from a knowledge base (`filterAddOn`)](https://learn.microsoft.com/azure/search/agentic-retrieval-how-to-retrieve)
- [Search index knowledge source (query hints are best effort)](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-search-index)
- [Connect to Azure AI Search using roles](https://learn.microsoft.com/azure/search/search-security-rbac) and [using identities](https://learn.microsoft.com/azure/search/search-security-rbac-client-code)
- [Service limits](https://learn.microsoft.com/azure/search/search-limits-quotas-capacity) and [tier features](https://learn.microsoft.com/azure/search/search-sku-tier)
- Repo: `docs/workspace-cosmos.md`, `src/savant/workspace.py`, `src/savant/bff_api.py`
