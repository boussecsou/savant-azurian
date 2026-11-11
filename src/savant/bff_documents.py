"""Owner-only routes for a project's documents (SDD-005 §7, phase 4).

Mounted by `bff_api` behind the same Easy Auth owner check as the chat, and only with the workspace
(the project must exist in Cosmos DB). The file travels as the raw request body (`?name=` gives its name),
so no form parser is needed. Nothing here logs a name, an id or content: failures are reported by kind.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from savant.document_library import MAX_BYTES, DocumentError, DocumentLibrary
from savant.workspace import WorkspaceService

logger = logging.getLogger("savant.bff")
_STATUS = {"invalid": 422, "unsupported": 415, "too_large": 413, "not_found": 404}


def _json(body, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


def create_documents_router(library: DocumentLibrary, workspace: WorkspaceService, require_owner) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{project_id}/documents", dependencies=[Depends(require_owner)])

    async def guarded(project_id: str, call):
        try:
            if not any(project["id"] == project_id for project in await workspace.projects()):
                raise DocumentError("not_found", "Unknown project.")
            return await call()
        except DocumentError as error:
            raise HTTPException(_STATUS[error.kind], error.message) from None
        except HTTPException:
            raise
        except Exception as error:
            logger.warning("documents_failed", extra={"error_type": type(error).__name__})
            raise HTTPException(502) from None

    @router.get("")
    async def list_documents(project_id: str):
        return _json(await guarded(project_id, lambda: library.list(project_id)))

    @router.post("")
    async def add_document(project_id: str, request: Request, name: str = ""):
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_BYTES:
            raise HTTPException(413, "Files are limited to 16 MB.")
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise HTTPException(413, "Files are limited to 16 MB.")
        document = await guarded(project_id, lambda: library.add(project_id, name, bytes(data)))
        logger.info("document_added", extra={"size_kb": len(data) // 1024})
        return _json(document, 201)

    @router.delete("/{document_id}")
    async def remove_document(project_id: str, document_id: str):
        await guarded(project_id, lambda: library.remove(project_id, document_id))
        return _json({}, 200)

    @router.get("/{document_id}/file")
    async def document_file(project_id: str, document_id: str):
        name, content_type, data = await guarded(project_id, lambda: library.file(project_id, document_id))
        # Inline, so a PDF opens in the browser's viewer; the name is encoded (RFC 5987). nosniff keeps
        # a text file as text. (A CSP sandbox would stop Chrome's PDF viewer.)
        return Response(
            data,
            media_type=content_type,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": f"inline; filename*=UTF-8''{quote(name)}",
            },
        )

    return router
