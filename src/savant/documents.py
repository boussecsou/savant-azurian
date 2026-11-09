"""Search the documents of the session's project in Azure AI Search (index built by scripts/search_setup.py).

The model only gives the question. The project comes from the request (`metadata.project_id`, set by the
BFF from the stored session) and is applied here as a filter, so a prompt can never read another
project's documents (SDD-005 D6). The query is hybrid (keywords + meaning, the question being embedded by
the index's own vectorizer) and re-ranked by the semantic ranker. Results are short passages with their
document's name: outside data, wrapped as untrusted by the caller like web and Notion results.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Annotated, Protocol

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TOOL_NAME = "search_documents"
API_VERSION = "2026-04-01"
SEARCH_SCOPE = "https://search.azure.com/.default"
# Same shape as the workspace ids (workspace.ID_PATTERN): no quote can reach the OData filter.
PROJECT_ID = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
# A document the owner can see in their list (the BFF names files {project}/{32 hex}/{name}). Anything
# else in the index (a file dropped by hand) is invisible to the owner, so it is never a source.
VISIBLE_DOCUMENT = re.compile(r"[0-9a-f]{32}")
MAX_RESULTS = 5
# One call may look at several angles of a question; the merged answer is bounded (the shared cap on a
# tool result is 20 000 characters, see reliability.py).
MAX_MERGED_RESULTS = 8
MAX_ANGLES = 4
MAX_PASSAGE_CHARS = 1200

INSTRUCTIONS = """

Project documents
- search_documents searches the documents the owner added to the current project (PDF, Word, slides,
text). Use it when the owner asks about their documents, files, notes or anything that may be written in
them. Search with a short, specific query. For a question with several angles (a summary, a list of limits,
the cases that fail...), make ONE call: put the main angle in `query` and the others in `more_queries`
(up to three): they are searched together and merged. Do not chain several calls one after the other:
each extra step costs several seconds. Name the document you used ("d'après savant-test.md, ..."). If nothing is found, say so plainly:
never invent content. It only sees the current project; other projects are never searched.
"""


def project_filter(project_id: str) -> str:
    """The OData filter that keeps a search inside one project. Refuses anything that is not an id."""
    if not isinstance(project_id, str) or not PROJECT_ID.fullmatch(project_id):
        raise ValueError("Invalid project id.")
    return f"project_id eq '{project_id}'"


class DocumentSearch(Protocol):
    async def search(self, query: str, *, project_id: str, top: int = MAX_RESULTS) -> list[dict]:
        """Passages of the project's documents: dicts with document_id, title and passage."""


class AzureDocumentSearch:
    """Hybrid + semantic query against the index, with an Entra token (Search Index Data Reader), no key."""

    def __init__(self, endpoint: str, index: str, token_provider, *, client: httpx.AsyncClient | None = None):
        self.url = f"{endpoint.rstrip('/')}/indexes('{index}')/docs/search?api-version={API_VERSION}"
        self._token = token_provider
        self._client = client

    async def search(self, query: str, *, project_id: str, top: int = MAX_RESULTS) -> list[dict]:
        body = {
            "search": query, "filter": project_filter(project_id), "top": top,
            "select": "document_id,title,chunk",
            "queryType": "semantic", "semanticConfiguration": "sa2-semantic", "captions": "extractive",
            "vectorQueries": [{"kind": "text", "text": query, "fields": "chunk_vector", "k": 20}],
        }
        # The token provider is synchronous (azure-identity caches the token): keep it off the event loop.
        token = await asyncio.to_thread(self._token)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        if self._client is not None:
            response = await self._client.post(self.url, json=body, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(self.url, json=body, headers=headers)
        # 429/5xx become transient errors for the shared retry; the body is never shown to the model.
        response.raise_for_status()
        return [_passage(item) for item in response.json().get("value", [])][:top]


def _passage(item: dict) -> dict:
    captions = item.get("@search.captions") or []
    caption = captions[0].get("text") if captions and isinstance(captions[0], dict) else None
    text = caption or item.get("chunk") or ""
    return {"document_id": str(item.get("document_id") or ""), "title": str(item.get("title") or ""),
            "passage": text[:MAX_PASSAGE_CHARS]}


class SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=300,
                       description="What to look for in the project's documents, in a few words.")
    more_queries: list[Annotated[str, Field(max_length=300)]] = Field(
        default_factory=list, max_length=MAX_ANGLES - 1,
        description="Other angles of the same question, searched together with `query` in this one call.")


def angles(query: str, more: list[str]) -> list[str]:
    """The distinct, non-blank queries of one call, in order (the main one first)."""
    seen, ordered = set(), []
    for text in [query, *more]:
        text = text.strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            ordered.append(text)
    return ordered[:MAX_ANGLES]


def merge(found: list[list[dict]]) -> list[dict]:
    """Passages of every angle, taken in turn by rank so each one is represented, without duplicates."""
    merged, seen = [], set()
    for rank in range(max((len(results) for results in found), default=0)):
        for results in found:
            if rank >= len(results):
                continue
            item = results[rank]
            key = (item["document_id"], item["passage"])
            if key not in seen:
                seen.add(key)
                merged.append(item)
    return merged[:MAX_MERGED_RESULTS]


def build_search_tool(search: DocumentSearch, project_id: str) -> StructuredTool:
    """The tool for one turn, bound to that turn's project: the model cannot pass or change it."""
    project_filter(project_id)

    async def search_documents(query: str, more_queries: list[str] | None = None) -> str:
        started = time.perf_counter()
        asked = angles(query, more_queries or [])
        found = await asyncio.gather(*(search.search(text, project_id=project_id) for text in asked))
        results = merge([[r for r in results if VISIBLE_DOCUMENT.fullmatch(r["document_id"])] for results in found])
        # Counts and timing only: never a query, a title or a passage.
        logger.info("documents_search angles=%d results=%d ms=%d", len(asked), len(results),
                    round((time.perf_counter() - started) * 1000))
        if not results:
            return json.dumps({"results": [], "message": "No passage of this project's documents matches."})
        return json.dumps({"results": results}, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=search_documents, name=TOOL_NAME, args_schema=SearchArgs,
        description="Search the documents of the current project (PDF, Word, slides, text) and return the "
                    "most relevant passages with their document name. Read-only.")
