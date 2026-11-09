"""The documents of a project (SDD-005 phase 4): files in Blob Storage, indexed by Azure AI Search.

The blob itself is the record: `documents/{projectId}/{documentId}/{file name}`, with metadata
`project_id` and `document_id` that the indexer copies onto every chunk (scripts/search_setup.py). The
state shown to the owner is read from the services, never guessed: "ready" once the index holds chunks
of the document, "failed" when the indexer reported an error for its file, else "indexing".

Removing a document removes its chunks from the index first, then its file (D8: what Savant no longer
shows, it no longer remembers). Blob deletion detection does not apply to chunked indexing, hence this
explicit order. `Files` and `SearchIndex` are interfaces so the rules are tested without Azure.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
import uuid
from typing import Protocol
from urllib.parse import unquote

from savant.workspace import ID_PATTERN

_ID = re.compile(ID_PATTERN)
_DOCUMENT_ID = re.compile(r"[0-9a-f]{32}")
# Any id the index may hold, hand-made ones included: no quote can reach the OData filter.
_INDEXED_ID = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
logger = logging.getLogger("savant.bff")
# What the indexer reads in this version (scripts/search_setup.py EXTENSIONS) and the Basic tier's limit.
EXTENSIONS = (".pdf", ".docx", ".pptx", ".txt", ".md")
MAX_BYTES = 16 * 1024 * 1024
NAME_MAX = 120
CONTENT_TYPES = {".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8", ".md": "text/markdown; charset=utf-8",
                 ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                 ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}


class DocumentError(Exception):
    """A rule was broken; `kind` maps to an HTTP status, `message` is safe to show."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


class Files(Protocol):
    async def list(self, prefix: str) -> list[dict]:
        """Blobs under the prefix: dicts with name, size, last_modified (ms) and metadata."""
    async def upload(self, name: str, data: bytes, content_type: str, metadata: dict) -> None: ...
    async def download(self, name: str) -> bytes: ...
    async def delete(self, name: str) -> None: ...
    async def close(self) -> None: ...


class SearchIndex(Protocol):
    async def ready(self, project_id: str) -> set[str]:
        """Ids of the project's documents that have at least one chunk in the index."""
    async def failed(self) -> set[str]:
        """Blob names the indexer reported an error for in its last run."""
    async def delete_document(self, project_id: str, document_id: str) -> None: ...
    async def busy(self) -> bool:
        """True while an indexer run is in progress (it may still write chunks of a removed file)."""
    async def run(self) -> None:
        """Start the indexer now (best effort: it also runs on a schedule)."""
    async def close(self) -> None: ...


def clean_name(raw: str) -> str:
    """A safe display and file name: no path, no control character, a supported extension."""
    name = unicodedata.normalize("NFC", (raw or "").replace("\\", "/").rsplit("/", 1)[-1])
    name = "".join(c for c in name if unicodedata.category(c)[0] != "C").strip().strip(".")
    if not name:
        raise DocumentError("invalid", "The file needs a name.")
    stem, dot, extension = name.rpartition(".")
    extension = "." + extension.lower() if dot else ""
    if extension not in EXTENSIONS:
        raise DocumentError("unsupported", "Supported files: " + ", ".join(EXTENSIONS) + ".")
    return stem[: NAME_MAX - len(extension)].strip() + extension


def _project(project_id: str) -> str:
    if not isinstance(project_id, str) or not _ID.fullmatch(project_id):
        raise DocumentError("invalid", "Unknown project.")
    return project_id


def _document(document_id: str) -> str:
    if not isinstance(document_id, str) or not _DOCUMENT_ID.fullmatch(document_id):
        raise DocumentError("not_found", "Unknown document.")
    return document_id


class DocumentLibrary:
    # After a removal, how often (s) and how many times the indexer is checked before a last clean-up.
    settle_interval = 5.0
    settle_checks = 40

    def __init__(self, files: Files, index: SearchIndex):
        self.files, self.index = files, index
        self._settling: set[asyncio.Task] = set()

    async def close(self) -> None:
        for task in list(self._settling):
            task.cancel()
        await self.files.close()
        await self.index.close()

    async def _blobs(self, project_id: str, listed: list[dict] | None = None) -> list[dict]:
        blobs = []
        for blob in listed if listed is not None else await self.files.list(f"{_project(project_id)}/"):
            parts = blob["name"].split("/")
            # Only well-formed entries of this project: {project}/{document}/{name}.
            if len(parts) == 3 and parts[0] == project_id and _DOCUMENT_ID.fullmatch(parts[1]):
                blobs.append({**blob, "document_id": parts[1], "file": parts[2]})
        return blobs

    async def _forget_orphans(self, project_id: str, ready: set[str], names: list[dict]) -> None:
        """Drop the chunks of documents whose file no longer exists.

        An indexer run that was already reading a file when it was removed writes its chunks after the
        removal, so the index remembers what was deleted. `ready` must have been read BEFORE the files
        are listed: a chunk can only follow its file, so an upload in flight is never taken for an orphan.
        Best effort: a failure here must not break the listing, the next one retries.
        """
        # Only the files the owner can see count: a file dropped by hand (non-standard id) is never listed,
        # so it must never be searchable either. Its file is left alone; only its chunks go.
        stored = {blob["document_id"] for blob in await self._blobs(project_id, names)}
        for document_id in sorted(ready - stored):
            try:
                await self.index.delete_document(project_id, document_id)
            except Exception:
                pass

    async def list(self, project_id: str) -> list[dict]:
        ready = await self.index.ready(_project(project_id))
        names = await self.files.list(f"{project_id}/")
        await self._forget_orphans(project_id, ready, names)
        blobs = await self._blobs(project_id, names)
        if not blobs:
            return []
        failed = await self.index.failed()
        documents = []
        for blob in sorted(blobs, key=lambda b: b.get("last_modified", 0), reverse=True):
            state = ("ready" if blob["document_id"] in ready else
                     "failed" if blob["name"] in failed else "indexing")
            documents.append({"id": blob["document_id"], "projectId": project_id, "name": blob["file"],
                              "size": blob.get("size", 0), "uploadedAt": blob.get("last_modified", 0), "state": state})
        return documents

    async def add(self, project_id: str, raw_name: str, data: bytes) -> dict:
        project_id, name = _project(project_id), clean_name(raw_name)
        if not data:
            raise DocumentError("invalid", "The file is empty.")
        if len(data) > MAX_BYTES:
            raise DocumentError("too_large", "Files are limited to 16 MB.")
        document_id = uuid.uuid4().hex
        extension = "." + name.rsplit(".", 1)[-1].lower()
        await self.files.upload(f"{project_id}/{document_id}/{name}", data, CONTENT_TYPES[extension],
                                {"project_id": project_id, "document_id": document_id})
        try:
            await self.index.run()
        except Exception:
            pass  # the schedule picks the file up anyway; the state stays "indexing" until then
        return {"id": document_id, "projectId": project_id, "name": name, "size": len(data),
                "uploadedAt": int(time.time() * 1000), "state": "indexing"}

    async def _one(self, project_id: str, document_id: str) -> dict:
        document_id = _document(document_id)
        for blob in await self._blobs(project_id):
            if blob["document_id"] == document_id:
                return blob
        raise DocumentError("not_found", "Unknown document.")

    async def file(self, project_id: str, document_id: str) -> tuple[str, str, bytes]:
        blob = await self._one(project_id, document_id)
        extension = "." + blob["file"].rsplit(".", 1)[-1].lower()
        return blob["file"], CONTENT_TYPES.get(extension, "application/octet-stream"), await self.files.download(blob["name"])

    async def remove(self, project_id: str, document_id: str) -> None:
        blob = await self._one(project_id, document_id)
        # Forget first (the index), then the file: never a file gone but still "remembered".
        await self.index.delete_document(project_id, blob["document_id"])
        await self.files.delete(blob["name"])
        # An indexer run that had already read the file writes its chunks after this: check again once
        # it is over, in the background (the owner does not wait for it).
        task = asyncio.get_running_loop().create_task(self.settle(project_id))
        self._settling.add(task)
        task.add_done_callback(self._settling.discard)

    async def settle(self, project_id: str) -> None:
        """Wait for the indexer run in progress (if any) to end, then forget what has no visible file."""
        try:
            for _ in range(self.settle_checks):
                if not await self.index.busy():
                    break
                await asyncio.sleep(self.settle_interval)
            await self._forget_orphans(project_id, await self.index.ready(project_id),
                                       await self.files.list(f"{_project(project_id)}/"))
        except Exception as error:
            # The next listing retries; never a name or an id in the log.
            logger.warning("documents_settle_failed", extra={"error_type": type(error).__name__})

    async def remove_project(self, project_id: str) -> None:
        for blob in await self._blobs(project_id):
            await self.index.delete_document(project_id, blob["document_id"])
            await self.files.delete(blob["name"])


# --- Azure ---------------------------------------------------------------------------------------


class BlobFiles:
    """The `documents` container, with the BFF's managed identity (Storage Blob Data Contributor)."""

    def __init__(self, account_url: str, container: str, credential):
        from azure.storage.blob.aio import ContainerClient
        self._container = ContainerClient(account_url, container, credential=credential)

    async def list(self, prefix: str) -> list[dict]:
        found = []
        async for blob in self._container.list_blobs(name_starts_with=prefix):
            modified = blob.last_modified.timestamp() * 1000 if blob.last_modified else 0
            found.append({"name": blob.name, "size": blob.size, "last_modified": int(modified)})
        return found

    async def upload(self, name: str, data: bytes, content_type: str, metadata: dict) -> None:
        from azure.storage.blob import ContentSettings
        await self._container.upload_blob(name, data, overwrite=False, metadata=metadata,
                                          content_settings=ContentSettings(content_type=content_type))

    async def download(self, name: str) -> bytes:
        stream = await self._container.download_blob(name)
        return await stream.readall()

    async def delete(self, name: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError
        try:
            await self._container.delete_blob(name)
        except ResourceNotFoundError:
            pass  # already gone

    async def close(self) -> None:
        await self._container.close()


class AzureSearchIndex:
    """The `sa2-docs` index and its indexer, with an Entra token (Search Index Data Contributor to read
    and delete chunks, Search Service Contributor to run the indexer and read its status). No key."""

    API = "api-version=2026-04-01"
    SCOPE = "https://search.azure.com/.default"

    def __init__(self, endpoint: str, index: str, indexer: str, credential, client=None):
        import httpx
        self.endpoint, self.index_name, self.indexer = endpoint.rstrip("/"), index, indexer
        self._credential = credential
        self._client = client or httpx.AsyncClient(timeout=20)

    async def _post(self, path: str, body: dict | None = None):
        token = await self._credential.get_token(self.SCOPE)
        response = await self._client.post(f"{self.endpoint}{path}?{self.API}", json=body,
                                           headers={"Authorization": f"Bearer {token.token}"})
        response.raise_for_status()
        return response

    PAGE = 1000  # the most a search returns, and the most an index batch accepts

    async def _chunks(self, filter_: str, select: str, *, paged: bool = True) -> list[dict]:
        """Chunks matching the filter. `paged` walks every page (skip); otherwise only the first one."""
        found, skip = [], 0
        while True:
            body = {"search": "*", "filter": filter_, "select": select, "top": self.PAGE}
            if skip:
                body["skip"] = skip
            response = await self._post(f"/indexes('{self.index_name}')/docs/search", body)
            page = response.json().get("value", [])
            found.extend(page)
            if not paged or len(page) < self.PAGE or skip >= 100_000 - self.PAGE:  # 100 000: the service's skip limit
                return found
            skip += self.PAGE

    async def ready(self, project_id: str) -> set[str]:
        return {item.get("document_id") for item in await self._chunks(f"project_id eq '{_project(project_id)}'",
                                                                        "document_id")}

    async def failed(self) -> set[str]:
        token = await self._credential.get_token(self.SCOPE)
        response = await self._client.get(f"{self.endpoint}/indexers('{self.indexer}')/status?{self.API}",
                                          headers={"Authorization": f"Bearer {token.token}"})
        response.raise_for_status()
        last = response.json().get("lastResult") or {}
        names = set()
        for error in last.get("errors") or []:
            text = " ".join(str(error.get(key) or "") for key in ("key", "name", "details", "errorMessage"))
            # The blob path appears in the error's key or name: keep the "{project}/{doc}/{file}" part.
            for match in re.finditer(r"([A-Za-z0-9_.:-]{1,64}/[0-9a-f]{32}/[^&\s\"]+)", text):
                names.add(unquote(match.group(1)))
        return names

    async def busy(self) -> bool:
        token = await self._credential.get_token(self.SCOPE)
        response = await self._client.get(f"{self.endpoint}/indexers('{self.indexer}')/status?{self.API}",
                                          headers={"Authorization": f"Bearer {token.token}"})
        response.raise_for_status()
        return ((response.json().get("lastResult") or {}).get("status") or "") == "inProgress"

    async def delete_document(self, project_id: str, document_id: str) -> None:
        if not isinstance(document_id, str) or not _INDEXED_ID.fullmatch(document_id):
            raise DocumentError("not_found", "Unknown document.")
        # Read the first page again after each batch instead of paging with skip (chunk_id is not sortable,
        # so a skip has no stable order); a document with many chunks takes a few rounds.
        filter_ = f"project_id eq '{_project(project_id)}' and document_id eq '{document_id}'"
        for _ in range(200):
            chunks = await self._chunks(filter_, "chunk_id", paged=False)
            if not chunks:
                return
            await self._post(f"/indexes('{self.index_name}')/docs/index",
                             {"value": [{"@search.action": "delete", "chunk_id": c["chunk_id"]} for c in chunks]})

    async def run(self) -> None:
        import httpx
        try:
            await self._post(f"/indexers('{self.indexer}')/run")
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 409:  # 409: already running, it will see the file
                raise

    async def close(self) -> None:
        await self._client.aclose()
