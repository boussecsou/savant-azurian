import asyncio

import pytest
from langchain_core.tools import StructuredTool

from savant.config import Settings
from savant.tools import notion


@pytest.fixture(autouse=True)
def oauth_callback_port_without_opening_a_socket(monkeypatch):
    # OAuth request-building tests never start a callback listener.
    monkeypatch.setattr("fastmcp.client.auth.oauth.find_available_port", lambda **_: 53123)


def _tool(name):
    async def invoke(**arguments):
        return arguments

    return StructuredTool.from_function(
        coroutine=invoke,
        name=name,
        description=f"{name} tool",
    )


def test_discovery_uses_oauth_and_exposes_only_allowlisted_tools(monkeypatch):
    captured = {}
    available = [_tool("search"), _tool("fetch"), _tool("update_page")]

    class FakeClient:
        def __init__(self, url, auth):
            captured["url"] = url
            captured["auth"] = auth

    class FakeAdapter:
        def __init__(self, client):
            captured["client"] = client

        async def list_tools(self, *, cache_mode):
            captured["cache_mode"] = cache_mode
            return available

    monkeypatch.setattr(notion, "Client", FakeClient)
    monkeypatch.setattr(notion, "MCPAdapter", FakeAdapter)
    settings = Settings(
        "https://model.example/openai/v1/",
        "model",
        notion_mcp_enabled=True,
        notion_read_tool_names=("search",),
        notion_write_tool_names=("update_page",),
    )

    tools = asyncio.run(notion.discover_notion_tools(settings))

    assert captured["url"] == "https://mcp.notion.com/mcp"
    assert captured["auth"].context.client_metadata.token_endpoint_auth_method == "none"
    assert captured["cache_mode"] == "bypass"
    assert [tool.name for tool in tools] == ["search", "update_page"]
    assert tools == [available[0], available[2]]


def test_discovery_reports_server_tool_names_for_configuration(monkeypatch):
    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

    class FakeAdapter:
        def __init__(self, _client):
            pass

        async def list_tools(self, **_kwargs):
            return [_tool("search"), _tool("fetch")]

    monkeypatch.setattr(notion, "Client", FakeClient)
    monkeypatch.setattr(notion, "MCPAdapter", FakeAdapter)
    settings = Settings(
        "https://model.example/openai/v1/",
        "model",
        notion_mcp_enabled=True,
    )

    with pytest.raises(RuntimeError, match="Available tools: fetch, search"):
        asyncio.run(notion.discover_notion_tools(settings))


def test_discovery_rejects_stale_allowlist_with_available_tool_names(monkeypatch):
    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

    class FakeAdapter:
        def __init__(self, _client):
            pass

        async def list_tools(self, **_kwargs):
            return [_tool("search")]

    monkeypatch.setattr(notion, "Client", FakeClient)
    monkeypatch.setattr(notion, "MCPAdapter", FakeAdapter)
    settings = Settings(
        "https://model.example/openai/v1/",
        "model",
        notion_mcp_enabled=True,
        notion_read_tool_names=("old_search",),
    )

    with pytest.raises(RuntimeError, match="old_search.*Available tools: search"):
        asyncio.run(notion.discover_notion_tools(settings))


@pytest.mark.parametrize("is_error", [False, True])
def test_native_mcp_conversion_preserves_results_and_server_errors(monkeypatch, is_error):
    from types import SimpleNamespace

    from fastmcp import Client
    from langchain.mcp import as_langchain_tool
    from mcp.types import TextContent, Tool

    calls = []

    async def enter(self):
        return self

    async def exit(self, *_args):
        pass

    async def call_tool(self, name, arguments, *, raise_on_error):
        calls.append((name, arguments, raise_on_error))
        return SimpleNamespace(
            content=[TextContent(type="text", text="not found" if is_error else "page content")],
            structured_content=None if is_error else {"page_id": "page"},
            is_error=is_error,
        )

    monkeypatch.setattr(Client, "__aenter__", enter)
    monkeypatch.setattr(Client, "__aexit__", exit)
    monkeypatch.setattr(Client, "call_tool", call_tool)

    async def invoke():
        client = Client("https://notion.example/mcp")
        remote_tool = Tool.model_validate(
            {
                "name": "fetch",
                "description": "Read a page.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "page_id": {"type": "string"},
                    },
                    "required": ["page_id"],
                },
            }
        )
        adapted = await as_langchain_tool(remote_tool, client)
        return await adapted.ainvoke(
            {
                "type": "tool_call",
                "name": "fetch",
                "args": {"page_id": "page"},
                "id": "mcp_call_1",
            }
        )

    result = asyncio.run(invoke())
    assert calls == [("fetch", {"page_id": "page"}, False)]
    assert result.tool_call_id == "mcp_call_1"
    assert result.status == ("error" if is_error else "success")
    assert result.content[0]["text"] == ("not found" if is_error else "page content")
    if not is_error:
        assert result.artifact == {"structured_content": {"page_id": "page"}}


def test_notion_oauth_registration_and_token_requests_use_one_auth_method():
    import json
    from urllib.parse import parse_qs

    from mcp.client.auth.utils import create_client_registration_request
    from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

    client = notion.build_notion_client("https://mcp.notion.com/mcp")
    # The public transport exposes the configured OAuth provider.
    oauth = client.transport.auth
    metadata = oauth.context.client_metadata
    registration = create_client_registration_request(None, metadata, "https://mcp.notion.com")
    assert json.loads(registration.content)["token_endpoint_auth_method"] == "none"

    oauth.context.client_info = OAuthClientInformationFull(
        client_id="test-client",
        token_endpoint_auth_method="none",
        redirect_uris=metadata.redirect_uris,
    )

    async def requests():
        exchange = await oauth._exchange_token_authorization_code("test-code", "test-verifier")
        oauth.context.current_tokens = OAuthToken(
            access_token="test-access", token_type="Bearer", refresh_token="test-refresh"
        )
        refresh = await oauth._refresh_token()
        return exchange, refresh

    exchange, refresh = asyncio.run(requests())
    for request in (exchange, refresh):
        form = parse_qs(request.content.decode())
        assert "Authorization" not in request.headers
        assert form["client_id"] == ["test-client"]
        assert "client_secret" not in form
    assert parse_qs(exchange.content.decode())["code_verifier"] == ["test-verifier"]
