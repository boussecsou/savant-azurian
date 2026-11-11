"""Discovery uses all actual pages and never returns a partial catalog."""

import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.tools import StructuredTool

from savant.config import Settings
from savant.tools.notion_chat import discover_tools


def test_pagination_annotations_and_bearer_remain_user_scoped(monkeypatch):
    captures, cursors = [], []
    read = StructuredTool.from_function(
        lambda: "read", name="fetch", description="Read", metadata={"annotations": {"readOnlyHint": True}}
    )
    write = StructuredTool.from_function(lambda: "write", name="update", description="Write")

    class Client:
        def __init__(self, endpoint, **kwargs):
            captures.append((endpoint, kwargs))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def list_tools_mcp(self, *, cursor, cache_mode):
            assert cache_mode == "bypass"
            cursors.append(cursor)
            return SimpleNamespace(
                tools=[read] if cursor is None else [write], next_cursor="page-2" if cursor is None else None
            )

    async def adapt(tool, client):
        return tool

    monkeypatch.setattr("savant.tools.notion_chat.Client", Client)
    monkeypatch.setattr("savant.tools.notion_chat.as_langchain_tool", adapt)
    settings = Settings("https://model/", "model")
    assert asyncio.run(discover_tools(settings, "private-token")) == [read, write]
    assert cursors == [None, "page-2"]
    import httpx2

    auth = captures[0][1]["auth"]
    request = next(auth.auth_flow(httpx2.Request("POST", captures[0][0])))
    assert request.headers["Authorization"] == "Bearer private-token"
    assert captures[0][0] == "https://mcp.notion.com/mcp"
    limited = Settings("https://model/", "model", notion_tool_policy="allowlist", notion_read_tool_names=("fetch",))
    assert asyncio.run(discover_tools(limited, "another-token")) == [read]


@pytest.mark.parametrize("duplicate", [False, True])
def test_cyclic_or_duplicate_catalog_fails_closed(monkeypatch, duplicate):
    tool = StructuredTool.from_function(lambda: "data", name="fetch", description="Read")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def list_tools_mcp(self, *, cursor, **kwargs):
            return SimpleNamespace(tools=[tool, tool] if duplicate else [], next_cursor=None if duplicate else "cycle")

    async def adapt(tool, client):
        return tool

    monkeypatch.setattr("savant.tools.notion_chat.Client", Client)
    monkeypatch.setattr("savant.tools.notion_chat.as_langchain_tool", adapt)
    with pytest.raises((ValueError, RuntimeError)):
        asyncio.run(discover_tools(Settings("https://model/", "model"), "token"))
