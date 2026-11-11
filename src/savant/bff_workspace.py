"""Owner-only routes for projects, sessions and messages (SDD-005 §7).

Mounted by `bff_api` behind the same Easy Auth owner check as the chat. Nothing here logs an id,
a title or a message: failures are reported by kind only (`bff_logging.py`).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from savant.workspace import ID_PATTERN, NAME_MAX, TITLE_MAX, WorkspaceError, WorkspaceService

logger = logging.getLogger("savant.bff")
_STATUS = {"invalid": 422, "not_found": 404, "conflict": 409, "protected": 409}


class ProjectIn(BaseModel):
    id: str | None = Field(default=None, pattern=f"^{ID_PATTERN}$")
    name: str = Field(min_length=1, max_length=NAME_MAX * 3)
    color: str | None = None


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, max_length=NAME_MAX * 3)
    color: str | None = None


class SessionIn(BaseModel):
    id: str | None = Field(default=None, pattern=f"^{ID_PATTERN}$")
    projectId: str = Field(pattern=f"^{ID_PATTERN}$")
    title: str = Field(min_length=1, max_length=TITLE_MAX * 3)
    pinned: bool = False


class SessionPatch(BaseModel):
    title: str | None = Field(default=None, max_length=TITLE_MAX * 3)
    titleEdited: bool | None = None
    pinned: bool | None = None
    projectId: str | None = Field(default=None, pattern=f"^{ID_PATTERN}$")


def _json(body, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


def create_workspace_router(service: WorkspaceService, require_owner, documents=None) -> APIRouter:
    router = APIRouter(prefix="/api", dependencies=[Depends(require_owner)])

    async def guarded(call):
        try:
            return await call
        except WorkspaceError as error:
            raise HTTPException(_STATUS[error.kind], error.message) from None
        except HTTPException:
            raise
        except Exception as error:
            # The kind of failure only: never the item involved.
            logger.warning("workspace_failed", extra={"error_type": type(error).__name__})
            raise HTTPException(502) from None

    @router.get("/projects")
    async def list_projects():
        return _json(await guarded(service.projects()))

    @router.post("/projects")
    async def create_project(body: ProjectIn):
        return _json(await guarded(service.create_project(body.id, body.name, body.color)), 201)

    @router.patch("/projects/{project_id}")
    async def patch_project(project_id: str, body: ProjectPatch):
        return _json(await guarded(service.update_project(project_id, body.name, body.color)))

    @router.delete("/projects/{project_id}")
    async def delete_project(project_id: str):
        await guarded(service.delete_project(project_id))
        if documents is not None:
            # D8: a deleted project's documents leave the index and the storage too. A failure here
            # leaves orphan files, never a visible project: it is logged, the deletion still stands.
            try:
                await documents.remove_project(project_id)
            except Exception as error:
                logger.warning("documents_cleanup_failed", extra={"error_type": type(error).__name__})
        return _json({}, 200)

    @router.get("/sessions")
    async def list_sessions(project: str | None = None):
        return _json(await guarded(service.sessions(project)))

    @router.post("/sessions")
    async def create_session(body: SessionIn):
        return _json(
            await guarded(service.create_session(body.id, body.projectId, body.title, pinned=body.pinned)), 201
        )

    @router.patch("/sessions/{session_id}")
    async def patch_session(session_id: str, body: SessionPatch):
        return _json(await guarded(service.update_session(session_id, body.model_dump(exclude_none=True))))

    @router.delete("/sessions/{session_id}")
    async def delete_session(session_id: str):
        await guarded(service.delete_session(session_id))
        return _json({}, 200)

    @router.get("/sessions/{session_id}/messages")
    async def session_messages(session_id: str):
        return _json(await guarded(service.messages(session_id)))

    return router
