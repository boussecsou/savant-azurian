"""The rules of the owner's workspace: projects, sessions and their messages (SDD-005 §4.2).

Everything belongs to a project; Main always exists and cannot be deleted; project names are unique
(case-insensitive); a session belongs to one project and can move; deleting a project or a session
deletes what it holds. Only text is stored: never tool arguments or results.
"""
from __future__ import annotations

import re
import time
from typing import Literal
import uuid

from savant.workspace_store import Store

MAIN_ID = "main"
MAIN_COLOR = "#6c80f2"
COLORS = ("#6c80f2", "#e0699b", "#3cb98a", "#e0a23c", "#4aa3d8", "#a077e8")
NAME_MAX = 40
TITLE_MAX = 200
TEXT_MAX = 100_000
ID_PATTERN = r"[A-Za-z0-9_.:-]{1,64}"
_ID = re.compile(ID_PATTERN)

Problem = Literal["invalid", "not_found", "conflict", "protected"]


class WorkspaceError(Exception):
    """A rule was broken; `kind` maps to an HTTP status, `message` is safe to show."""

    def __init__(self, kind: Problem, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


def _now() -> int:
    return int(time.time() * 1000)


class WorkspaceService:
    def __init__(self, store: Store):
        self.store = store

    async def close(self) -> None:
        await self.store.close()

    # --- projects ---------------------------------------------------------------------------

    async def projects(self) -> list[dict]:
        projects = await self.store.projects()
        if not any(p["id"] == MAIN_ID for p in projects):
            main = {"id": MAIN_ID, "name": "Main", "color": MAIN_COLOR, "system": True, "createdAt": _now()}
            await self.store.put_project(main)
            projects = [main, *projects]
        return sorted(projects, key=lambda p: (p["id"] != MAIN_ID, p.get("createdAt", 0)))

    async def _project(self, project_id: str) -> dict:
        for project in await self.projects():
            if project["id"] == project_id:
                return project
        raise WorkspaceError("not_found", "Unknown project.")

    @staticmethod
    def _name(name: str) -> str:
        name = " ".join(name.split())
        if not name or len(name) > NAME_MAX:
            raise WorkspaceError("invalid", f"A project name has 1 to {NAME_MAX} characters.")
        return name

    async def _check_unique(self, name: str, own_id: str | None) -> None:
        for project in await self.projects():
            if project["id"] != own_id and project["name"].casefold() == name.casefold():
                raise WorkspaceError("conflict", "A project with this name already exists.")

    async def create_project(self, project_id: str | None, name: str, color: str | None) -> dict:
        project_id = project_id or uuid.uuid4().hex
        if not _ID.fullmatch(project_id) or project_id == MAIN_ID:
            raise WorkspaceError("invalid", "Invalid project id.")
        if color is not None and color not in COLORS:
            raise WorkspaceError("invalid", "Unknown color.")
        name = self._name(name)
        if any(p["id"] == project_id for p in await self.projects()):
            raise WorkspaceError("conflict", "This project already exists.")
        await self._check_unique(name, None)
        project = {"id": project_id, "name": name, "color": color or COLORS[1], "createdAt": _now()}
        await self.store.put_project(project)
        return project

    async def update_project(self, project_id: str, name: str | None, color: str | None) -> dict:
        project = await self._project(project_id)
        if name is not None:
            if project.get("system"):
                raise WorkspaceError("protected", "Main cannot be renamed.")
            name = self._name(name)
            await self._check_unique(name, project_id)
            project = {**project, "name": name}
        if color is not None:
            if color not in COLORS:
                raise WorkspaceError("invalid", "Unknown color.")
            project = {**project, "color": color}
        await self.store.put_project(project)
        return project

    async def delete_project(self, project_id: str) -> None:
        project = await self._project(project_id)
        if project.get("system"):
            raise WorkspaceError("protected", "Main cannot be deleted.")
        for session in await self.store.sessions():
            if session["projectId"] == project_id:
                await self.store.delete_session(session["id"])
        await self.store.delete_project(project_id)

    # --- sessions ---------------------------------------------------------------------------

    async def sessions(self, project_id: str | None = None) -> list[dict]:
        found = [s for s in await self.store.sessions() if project_id in (None, s["projectId"])]
        return sorted(found, key=lambda s: s.get("updatedAt", 0), reverse=True)

    async def session(self, session_id: str) -> dict:
        found = await self.store.get_session(session_id)
        if found is None:
            raise WorkspaceError("not_found", "Unknown session.")
        return found

    @staticmethod
    def _title(title: str) -> str:
        title = " ".join(title.split())
        if not title or len(title) > TITLE_MAX:
            raise WorkspaceError("invalid", f"A session title has 1 to {TITLE_MAX} characters.")
        return title

    async def create_session(self, session_id: str | None, project_id: str, title: str,
                             *, pinned: bool = False) -> dict:
        session_id = session_id or uuid.uuid4().hex
        if not _ID.fullmatch(session_id):
            raise WorkspaceError("invalid", "Invalid session id.")
        await self._project(project_id)
        if await self.store.get_session(session_id) is not None:
            raise WorkspaceError("conflict", "This session already exists.")
        session = {"id": session_id, "projectId": project_id, "title": self._title(title),
                   "pinned": pinned, "updatedAt": _now(), "messageCount": 0}
        await self.store.put_session(session)
        return session

    async def update_session(self, session_id: str, changes: dict) -> dict:
        """`changes` may hold title, titleEdited, pinned and projectId; anything else is ignored."""
        session = await self.session(session_id)
        if changes.get("title") is not None:
            session = {**session, "title": self._title(changes["title"])}
        if changes.get("titleEdited") is not None:
            session = {**session, "titleEdited": bool(changes["titleEdited"])}
        if changes.get("pinned") is not None:
            session = {**session, "pinned": bool(changes["pinned"])}
        if changes.get("projectId") is not None:
            await self._project(changes["projectId"])
            session = {**session, "projectId": changes["projectId"]}
        await self.store.put_session(session)
        return session

    async def delete_session(self, session_id: str) -> None:
        await self.session(session_id)
        await self.store.delete_session(session_id)

    # --- messages ---------------------------------------------------------------------------

    async def messages(self, session_id: str) -> list[dict]:
        await self.session(session_id)
        return await self.store.messages(session_id)

    async def record_turn(self, session_id: str, question: str, answer: str, *,
                          voice: bool, response_id: str | None) -> dict:
        """Keep one finished turn and remember the agent's answer id, which continues the thread."""
        session = await self.session(session_id)
        at = _now()
        turn = [
            {"id": uuid.uuid4().hex, "role": "user", "text": question[:TEXT_MAX], "at": at,
             **({"voice": True} if voice else {})},
            {"id": uuid.uuid4().hex, "role": "assistant", "text": answer[:TEXT_MAX], "at": at + 1,
             **({"voice": True} if voice else {})},
        ]
        await self.store.put_messages(session_id, turn)
        session = {**session, "updatedAt": at, "messageCount": session.get("messageCount", 0) + 2,
                   **({"conversationId": response_id} if response_id else {})}
        await self.store.put_session(session)
        return session
