"""Create (or update) the document RAG pipeline in Azure AI Search: index, data source, skillset, indexer.

Azure does the chunking, the embeddings and the indexing itself ("integrated vectorization"): the indexer
reads the `documents` Blob container, the skillset splits each file into chunks and embeds them with the
embedding deployment, and the index receives one search document per chunk. A vectorizer in the index
embeds the question at query time. Our code only drops files in Blob Storage and queries the index.

Every chunk carries `project_id` and `document_id`, copied from the blob's metadata. `project_id` is
filterable from the first version of the index (an existing field cannot be made filterable later): the
agent always adds `project_id eq '<project>'` itself, the model never chooses it.

Without --apply, print the four definitions and exit: no credential, no request. With --apply, PUT them
(create or update) with your Entra identity (`DefaultAzureCredential`), no key. Run it from the repository
root, after the manual portal steps (docs/search-documents.md):

    uv run --locked python -m scripts.search_setup            # show the definitions
    uv run --locked python -m scripts.search_setup --apply    # create or update them

Configuration (environment or .env): SEARCH_ENDPOINT, SEARCH_STORAGE_RESOURCE_ID,
SEARCH_EMBEDDING_ENDPOINT, SEARCH_EMBEDDING_DEPLOYMENT; optional SEARCH_EMBEDDING_MODEL
(text-embedding-3-small), SEARCH_DOCUMENTS_CONTAINER (documents), SEARCH_INDEX (sa2-docs).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass

API_VERSION = "2026-04-01"
SEARCH_SCOPE = "https://search.azure.com/.default"
LABELS = {"indexes": "index", "datasources": "data source", "skillsets": "skillset", "indexers": "indexer"}
# text-embedding-3-small produces at most 1536 dimensions; the skill and the vector field must agree.
DIMENSIONS = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072, "text-embedding-ada-002": 1536}
# File types the indexer reads in this first version: text-based documents. Images and scanned PDFs need
# OCR (a billed skill) and come later.
EXTENSIONS = (".pdf", ".docx", ".pptx", ".txt", ".md")
# Chunk size in characters, and overlap so a sentence cut at a boundary is still found whole.
CHUNK_CHARS = 2000
CHUNK_OVERLAP = 300


@dataclass(frozen=True)
class Config:
    search_endpoint: str
    storage_resource_id: str
    embedding_endpoint: str
    embedding_deployment: str
    embedding_model: str = "text-embedding-3-small"
    container: str = "documents"
    index: str = "sa2-docs"

    @property
    def names(self) -> dict[str, str]:
        return {
            "index": self.index,
            "datasource": f"{self.index}-blob",
            "skillset": f"{self.index}-skillset",
            "indexer": f"{self.index}-indexer",
        }

    @property
    def dimensions(self) -> int:
        return DIMENSIONS[self.embedding_model]


def config_from_env(env=os.environ) -> Config:
    """Fail fast with every missing or malformed value named, before any request."""
    required = {
        "SEARCH_ENDPOINT": r"https://[a-z0-9-]+\.search\.windows\.net/?",
        "SEARCH_STORAGE_RESOURCE_ID": r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\.Storage/"
        r"storageAccounts/[a-z0-9]+",
        # The embedding resource needs a custom subdomain (doc: integrated vectorization prerequisites).
        "SEARCH_EMBEDDING_ENDPOINT": r"https://[a-z0-9-]+\.(openai\.azure\.com|cognitiveservices\.azure\.com|"
        r"services\.ai\.azure\.com)/?",
        "SEARCH_EMBEDDING_DEPLOYMENT": r"[A-Za-z0-9._-]{1,64}",
    }
    values, problems = {}, []
    for name, pattern in required.items():
        value = env.get(name, "").strip()
        if not re.fullmatch(pattern, value):
            problems.append(name)
        values[name] = value.rstrip("/")
    model = env.get("SEARCH_EMBEDDING_MODEL", "text-embedding-3-small").strip()
    if model not in DIMENSIONS:
        problems.append("SEARCH_EMBEDDING_MODEL")
    container = env.get("SEARCH_DOCUMENTS_CONTAINER", "documents").strip()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])", container):
        problems.append("SEARCH_DOCUMENTS_CONTAINER")
    index = env.get("SEARCH_INDEX", "sa2-docs").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,100}", index):
        problems.append("SEARCH_INDEX")
    if problems:
        raise ValueError("Missing or invalid: " + ", ".join(problems) + " (see docs/search-documents.md).")
    return Config(
        values["SEARCH_ENDPOINT"],
        values["SEARCH_STORAGE_RESOURCE_ID"],
        values["SEARCH_EMBEDDING_ENDPOINT"],
        values["SEARCH_EMBEDDING_DEPLOYMENT"],
        model,
        container,
        index,
    )


def _embedding(cfg: Config) -> dict:
    # No apiKey: the search service calls the model with its own managed identity
    # (Cognitive Services OpenAI User on the embedding resource, fp-savant-azurian-2-resource).
    return {
        "resourceUri": cfg.embedding_endpoint,
        "deploymentId": cfg.embedding_deployment,
        "modelName": cfg.embedding_model,
    }


def index_definition(cfg: Config) -> dict:
    """One search document per chunk. Only what the agent needs to search, filter and cite."""
    return {
        "name": cfg.index,
        "fields": [
            # Key generated by the index projection; the keyword analyzer is required for projected keys.
            {
                "name": "chunk_id",
                "type": "Edm.String",
                "key": True,
                "searchable": True,
                "analyzer": "keyword",
                "retrievable": True,
                "filterable": False,
                "sortable": False,
                "facetable": False,
            },
            {
                "name": "parent_id",
                "type": "Edm.String",
                "searchable": False,
                "filterable": True,
                "retrievable": True,
                "sortable": False,
                "facetable": False,
            },
            {
                "name": "project_id",
                "type": "Edm.String",
                "searchable": False,
                "filterable": True,
                "retrievable": True,
                "sortable": False,
                "facetable": False,
            },
            {
                "name": "document_id",
                "type": "Edm.String",
                "searchable": False,
                "filterable": True,
                "retrievable": True,
                "sortable": False,
                "facetable": False,
            },
            {
                "name": "title",
                "type": "Edm.String",
                "searchable": True,
                "filterable": False,
                "retrievable": True,
                "sortable": False,
                "facetable": False,
            },
            {
                "name": "chunk",
                "type": "Edm.String",
                "searchable": True,
                "filterable": False,
                "retrievable": True,
                "sortable": False,
                "facetable": False,
            },
            {
                "name": "chunk_vector",
                "type": "Collection(Edm.Single)",
                "searchable": True,
                "retrievable": False,
                "stored": False,
                "dimensions": cfg.dimensions,
                "vectorSearchProfile": "sa2-hnsw-profile",
            },
        ],
        "vectorSearch": {
            "algorithms": [
                {
                    "name": "sa2-hnsw",
                    "kind": "hnsw",
                    "hnswParameters": {"m": 4, "efConstruction": 400, "efSearch": 100, "metric": "cosine"},
                }
            ],
            "profiles": [{"name": "sa2-hnsw-profile", "algorithm": "sa2-hnsw", "vectorizer": "sa2-openai"}],
            "vectorizers": [{"name": "sa2-openai", "kind": "azureOpenAI", "azureOpenAIParameters": _embedding(cfg)}],
        },
        "semantic": {
            "defaultConfiguration": "sa2-semantic",
            "configurations": [
                {
                    "name": "sa2-semantic",
                    "prioritizedFields": {
                        "titleField": {"fieldName": "title"},
                        "prioritizedContentFields": [{"fieldName": "chunk"}],
                    },
                }
            ],
        },
    }


def datasource_definition(cfg: Config) -> dict:
    # "ResourceId=..." means: connect with the search service's managed identity (Storage Blob Data Reader).
    # No deletion detection policy: it does not apply to one-to-many (chunked) indexing, so the BFF deletes
    # a document's chunks itself (filter document_id eq '<id>') before deleting its blob.
    return {
        "name": cfg.names["datasource"],
        "type": "azureblob",
        "credentials": {"connectionString": f"ResourceId={cfg.storage_resource_id};"},
        "container": {"name": cfg.container},
    }


def skillset_definition(cfg: Config) -> dict:
    names = cfg.names
    return {
        "name": names["skillset"],
        "description": "Split each document into chunks and embed them (integrated vectorization).",
        "skills": [
            {
                "@odata.type": "#Microsoft.Skills.Text.SplitSkill",
                "name": "split",
                "context": "/document",
                "textSplitMode": "pages",
                "maximumPageLength": CHUNK_CHARS,
                "pageOverlapLength": CHUNK_OVERLAP,
                # Lengths are in characters ("unit" exists only in preview API versions).
                "inputs": [{"name": "text", "source": "/document/content"}],
                "outputs": [{"name": "textItems", "targetName": "pages"}],
            },
            {
                "@odata.type": "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill",
                "name": "embed",
                "context": "/document/pages/*",
                **_embedding(cfg),
                "dimensions": cfg.dimensions,
                "inputs": [{"name": "text", "source": "/document/pages/*"}],
                "outputs": [{"name": "embedding", "targetName": "vector"}],
            },
        ],
        "indexProjections": {
            "selectors": [
                {
                    "targetIndexName": cfg.index,
                    "parentKeyFieldName": "parent_id",
                    "sourceContext": "/document/pages/*",
                    "mappings": [
                        {"name": "chunk", "source": "/document/pages/*"},
                        {"name": "chunk_vector", "source": "/document/pages/*/vector"},
                        # The file name, as uploaded by the BFF ({projectId}/{documentId}/{name}).
                        {"name": "title", "source": "/document/metadata_storage_name"},
                        # Custom blob metadata set by the BFF at upload: the chunk's project and document.
                        {"name": "project_id", "source": "/document/project_id"},
                        {"name": "document_id", "source": "/document/document_id"},
                    ],
                }
            ],
            # Chunks only: no parent documents in the index.
            "parameters": {"projectionMode": "skipIndexingParentDocuments"},
        },
    }


def indexer_definition(cfg: Config) -> dict:
    names = cfg.names
    return {
        "name": names["indexer"],
        "dataSourceName": names["datasource"],
        "targetIndexName": cfg.index,
        "skillsetName": names["skillset"],
        # The BFF runs the indexer right after an upload; the schedule only catches what was missed.
        "schedule": {"interval": "PT30M"},
        "parameters": {
            "configuration": {
                "dataToExtract": "contentAndMetadata",
                "indexedFileNameExtensions": ",".join(EXTENSIONS),
                "failOnUnsupportedContentType": False,
                "failOnUnprocessableDocument": False,
            },
            # One bad file must not stop the others; failures stay visible in the indexer status.
            "maxFailedItems": -1,
            "maxFailedItemsPerBatch": -1,
        },
        # No fieldMappings: parent documents are not indexed, the projections above carry every field.
    }


def definitions(cfg: Config) -> list[tuple[str, dict]]:
    """In creation order: the index and the data source before the skillset, the indexer last."""
    return [
        ("indexes", index_definition(cfg)),
        ("datasources", datasource_definition(cfg)),
        ("skillsets", skillset_definition(cfg)),
        ("indexers", indexer_definition(cfg)),
    ]


def apply(cfg: Config) -> int:
    import httpx
    from azure.identity import DefaultAzureCredential

    token = DefaultAzureCredential().get_token(SEARCH_SCOPE).token
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    with httpx.Client(timeout=60) as client:
        for collection, body in definitions(cfg):
            url = f"{cfg.search_endpoint}/{collection}('{body['name']}')?api-version={API_VERSION}"
            response = client.put(url, headers=headers, json=body)
            # Status and the service's own message only: it never contains a token.
            print(f"{LABELS[collection]} {body['name']}: HTTP {response.status_code}")
            if response.status_code >= 400:
                print(response.text[:800], file=sys.stderr)
                return 1
    print("Done. The indexer runs once now, then every 30 minutes; the BFF will also run it after an upload.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Create or update the definitions in Azure")
    args = parser.parse_args(argv)
    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
    except ImportError:
        pass
    try:
        cfg = config_from_env()
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    if not args.apply:
        for collection, body in definitions(cfg):
            print(f"### {collection} {body['name']}\n{json.dumps(body, indent=2)}\n")
        print("Nothing was sent. Add --apply to create or update these definitions.")
        return 0
    return apply(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
