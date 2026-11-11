"""Where the owner's projects, sessions and messages are kept (SDD-005 §4, §6).

`Store` is a plain create/read/update/delete interface: no rule lives here (see `workspace.py`), so
the rules are tested once with an in-memory copy and the Cosmos DB copy stays thin. Items are
dictionaries shaped like the PWA's own model (camelCase). Cosmos DB adds its own `_`-prefixed system
fields; they never leave this module.

Partition keys, fixed when the containers were created: projects `/id`, sessions `/id`,
messages `/sessionId`. One owner only: nothing here tells owners apart.
"""

from __future__ import annotations

from typing import Any, Protocol

DEFAULT_DATABASE = "sa2"


class Store(Protocol):
    async def projects(self) -> list[dict]: ...
    async def put_project(self, project: dict) -> None: ...
    async def delete_project(self, project_id: str) -> None: ...
    async def sessions(self) -> list[dict]: ...
    async def get_session(self, session_id: str) -> dict | None: ...
    async def put_session(self, session: dict) -> None: ...
    async def delete_session(self, session_id: str) -> None: ...
    async def messages(self, session_id: str) -> list[dict]: ...
    async def put_messages(self, session_id: str, messages: list[dict]) -> None: ...
    async def close(self) -> None: ...


def _clean(item: dict) -> dict:
    """Drop Cosmos DB's system fields (`_rid`, `_etag`, `_ts`...)."""
    return {key: value for key, value in item.items() if not key.startswith("_")}


class CosmosStore:
    """The `Store` on Azure Cosmos DB for NoSQL, authenticated with Microsoft Entra (no key)."""

    def __init__(self, endpoint: str, credential: Any, database: str = DEFAULT_DATABASE):
        from azure.cosmos.aio import CosmosClient

        self._client = CosmosClient(endpoint, credential=credential)
        db = self._client.get_database_client(database)
        self._projects = db.get_container_client("projects")
        self._sessions = db.get_container_client("sessions")
        self._messages = db.get_container_client("messages")

    @staticmethod
    async def _all(container, query: str, **kwargs) -> list[dict]:
        return [_clean(item) async for item in container.query_items(query, **kwargs)]

    async def projects(self) -> list[dict]:
        return await self._all(self._projects, "SELECT * FROM c")

    async def put_project(self, project: dict) -> None:
        await self._projects.upsert_item(project)

    async def delete_project(self, project_id: str) -> None:
        await self._delete(self._projects, project_id, project_id)

    async def sessions(self) -> list[dict]:
        return await self._all(self._sessions, "SELECT * FROM c")

    async def get_session(self, session_id: str) -> dict | None:
        found = await self._all(
            self._sessions,
            "SELECT * FROM c WHERE c.id = @id",
            parameters=[{"name": "@id", "value": session_id}],
            partition_key=session_id,
        )
        return found[0] if found else None

    async def put_session(self, session: dict) -> None:
        await self._sessions.upsert_item(session)

    async def delete_session(self, session_id: str) -> None:
        # The messages share the session's id as partition key: one partition, then the session itself.
        for message in await self.messages(session_id):
            await self._delete(self._messages, message["id"], session_id)
        await self._delete(self._sessions, session_id, session_id)

    async def messages(self, session_id: str) -> list[dict]:
        return await self._all(
            self._messages,
            "SELECT * FROM c WHERE c.sessionId = @id ORDER BY c.at",
            parameters=[{"name": "@id", "value": session_id}],
            partition_key=session_id,
        )

    async def put_messages(self, session_id: str, messages: list[dict]) -> None:
        for message in messages:
            await self._messages.upsert_item({**message, "sessionId": session_id})

    @staticmethod
    async def _delete(container, item_id: str, partition_key: str) -> None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            await container.delete_item(item_id, partition_key=partition_key)
        except CosmosResourceNotFoundError:
            pass  # already gone: deleting twice is not an error

    async def close(self) -> None:
        await self._client.close()
