import asyncio

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from savant.config import Settings
from savant.tools.notion_foundry import build_foundry_graph


@pytest.mark.parametrize("backend, endpoint", [("unknown", "https://project"), ("foundry", "")])
def test_invalid_foundry_configuration_fails_before_startup(monkeypatch, backend, endpoint):
    monkeypatch.setattr("savant.config.load_dotenv", lambda **_: None)
    monkeypatch.setenv("AZURE_OPENAI_BASE_URL", "https://model/")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "model")
    monkeypatch.setenv("NOTION_MCP_ENABLED", "true")
    monkeypatch.setenv("NOTION_BACKEND", backend)
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", endpoint)
    monkeypatch.delenv("AZURE_AI_PROJECT_ENDPOINT", raising=False)
    with pytest.raises(RuntimeError):
        Settings.from_env()


@pytest.mark.parametrize("approved, platform_approval", [(True, False), (False, False), (True, True)])
def test_foundry_tools_discovered_once_then_cached_and_writes_approved(monkeypatch, approved, platform_approval):
    calls, discoveries, exposed = [], [], []
    read = StructuredTool.from_function(lambda: "page", name="notion___fetch", description="Read")
    write = StructuredTool.from_function(
        lambda: calls.append("write") or "done", name="notion___update", description="Write"
    )
    hidden = StructuredTool.from_function(lambda: "hidden", name="other___delete", description="Hidden")

    class Toolbox:
        def __init__(self, **kwargs):
            pass

        async def get_tools(self):
            discoveries.append(1)
            return [read, write, hidden]

        async def get_tools_requiring_approval(self):
            return [write.name] if platform_approval else []

    class Model:
        async def ainvoke(self, messages):
            if any(getattr(m, "tool_call_id", None) for m in messages):
                return AIMessage(content="finished")
            return AIMessage(content="", tool_calls=[{"name": write.name, "args": {}, "id": "write-1"}])

    monkeypatch.setattr("savant.tools.notion_foundry.AzureAIProjectToolbox", Toolbox)
    settings = Settings(
        "https://model/",
        "model",
        notion_backend="foundry",
        notion_read_tool_names=(read.name, write.name) if platform_approval else (read.name,),
        notion_write_tool_names=() if platform_approval else (write.name,),
    )

    def factory(tools):
        exposed.extend(t.name for t in tools)
        return Model()

    graph = build_foundry_graph(settings, factory, MemorySaver())
    assert discoveries == []

    async def run():
        config = {"configurable": {"thread_id": "conversation"}}
        pending = await graph.ainvoke({"messages": ["Update"]}, config)
        assert calls == []
        interruption = pending["__interrupt__"][0]
        assert interruption.value["tool_name"] == write.name
        await graph.ainvoke(Command(resume=interruption.value if approved else False), config)
        assert calls == (["write"] if approved else [])
        # Listed once, then reused by every step of both turns (TOOLBOX_CACHE_SECONDS).
        assert discoveries == [1]
        assert hidden.name not in exposed

    asyncio.run(run())


def test_foundry_consent_surfaces_and_discovery_retries(monkeypatch):
    consent = StructuredTool.from_function(
        lambda query: "Open https://consent.example then restart the agent",
        name="oauth_consent_required",
        description="Consent",
    )

    class Toolbox:
        def __init__(self, **kwargs):
            self.calls = 0

        async def get_tools(self):
            self.calls += 1
            return [consent]

    monkeypatch.setattr("savant.tools.notion_foundry.AzureAIProjectToolbox", Toolbox)
    graph = build_foundry_graph(
        Settings("https://model/", "model"), lambda _: pytest.fail("No model call during consent"), MemorySaver()
    )

    async def run():
        for thread in ["user-one", "user-two"]:
            result = await graph.ainvoke({"messages": ["Read"]}, {"configurable": {"thread_id": thread}})
            assert "send your request again" in result["messages"][-1].content

    asyncio.run(run())


def test_versioned_toolbox_exposes_all_tools_and_honors_platform_approval(monkeypatch):
    endpoint = "https://account.services.ai.azure.com/api/projects/project/toolboxes/lab/versions/2/mcp?api-version=v1"
    from savant.tools.notion_foundry import EndpointToolbox

    real = EndpointToolbox(project_endpoint="https://project", toolbox_name="lab", mcp_endpoint=endpoint)
    assert real.toolbox_endpoint == endpoint
    calls, exposed = [], []
    write = StructuredTool.from_function(lambda: calls.append(1) or "done", name="lab___write", description="Write")

    class Toolbox:
        def __init__(self, **kwargs):
            assert kwargs["mcp_endpoint"] == endpoint

        async def get_tools(self):
            return [write]

        async def get_tools_requiring_approval(self):
            return [write.name]

    class Model:
        async def ainvoke(self, messages):
            if any(getattr(m, "tool_call_id", None) for m in messages):
                return AIMessage(content="done")
            return AIMessage(content="", tool_calls=[{"name": write.name, "args": {}, "id": "one"}])

    monkeypatch.setattr("savant.tools.notion_foundry.EndpointToolbox", Toolbox)

    def factory(tools):
        exposed.extend(t.name for t in tools)
        return Model()

    graph = build_foundry_graph(Settings("https://model/", "model", toolbox_endpoint=endpoint), factory, MemorySaver())

    async def run():
        config = {"configurable": {"thread_id": "toolbox"}}
        result = await graph.ainvoke({"messages": ["write"]}, config)
        assert calls == []
        assert write.name in exposed
        pending = result["__interrupt__"][0].value
        await graph.ainvoke(Command(resume=pending), config)
        assert calls == [1]

    asyncio.run(run())


@pytest.mark.parametrize("version_path", ["", "/versions/2"])
def test_endpoint_transport_preserves_url_and_refreshes_auth(monkeypatch, version_path):
    import httpx2
    from azure.core.credentials import AccessToken

    from savant.tools.notion_foundry import EndpointToolbox

    class Credential:
        def get_token(self, *scopes, **kwargs):
            assert scopes == ("https://ai.azure.com/.default",)
            return AccessToken("test-token", 4102444800)

    endpoint = (
        f"https://account.services.ai.azure.com/api/projects/project/toolboxes/lab{version_path}/mcp?api-version=v1"
    )
    captured = []

    class Transport:
        def __init__(self, url, headers, auth):
            assert url == endpoint
            assert headers["Foundry-Features"] == "Toolboxes=V1Preview"
            request = httpx2.Request("POST", url)
            assert next(auth.auth_flow(request)).headers["Authorization"] == "Bearer test-token"
            captured.append(url)

    class Adapter:
        def __init__(self, client):
            pass

        async def list_tools(self, cache_mode):
            assert cache_mode == "bypass"
            return []

    monkeypatch.setattr("fastmcp.client.transports.StreamableHttpTransport", Transport)
    monkeypatch.setattr("fastmcp.Client", lambda transport, mode: transport)
    monkeypatch.setattr("langchain.mcp.MCPAdapter", Adapter)
    toolbox = EndpointToolbox(
        project_endpoint="https://project", toolbox_name="lab", mcp_endpoint=endpoint, credential=Credential()
    )
    assert asyncio.run(toolbox.get_tools()) == []
    assert captured == [endpoint]


def test_endpoint_toolbox_lists_tools_from_toolbox_without_2026_cache_fields(monkeypatch):
    """The live toolbox accepts server/discover at 2026-07-28 but its tools/list
    lacks that revision's required fields; discovery must still succeed."""
    import json

    import httpx2
    from azure.core.credentials import AccessToken
    from fastmcp.client.transports import StreamableHttpTransport

    from savant.tools.notion_foundry import EndpointToolbox

    class Credential:
        def get_token(self, *scopes, **kwargs):
            return AccessToken("test-token", 4102444800)

    def handler(request):
        message = json.loads(request.content)
        if "id" not in message:
            return httpx2.Response(202)
        result = {
            "server/discover": {
                "resultType": "complete",
                "ttlMs": 0,
                "cacheScope": "private",
                "supportedVersions": ["2026-07-28"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "toolbox", "version": "1"},
            },
            "initialize": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "toolbox", "version": "1"},
            },
            "tools/list": {"tools": [{"name": "notion-search", "inputSchema": {"type": "object"}}]},
        }[message["method"]]
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})

    def client_factory(**kwargs):
        kwargs.pop("timeout", None)
        return httpx2.AsyncClient(transport=httpx2.MockTransport(handler), **kwargs)

    class Transport(StreamableHttpTransport):
        def __init__(self, url, headers, auth):
            super().__init__(url, headers=headers, auth=auth, httpx_client_factory=client_factory)

    monkeypatch.setattr("fastmcp.client.transports.StreamableHttpTransport", Transport)
    endpoint = "https://account.services.ai.azure.com/api/projects/project/toolboxes/lab/mcp?api-version=v1"
    toolbox = EndpointToolbox(
        project_endpoint="https://project", toolbox_name="lab", mcp_endpoint=endpoint, credential=Credential()
    )
    assert [tool.name for tool in asyncio.run(toolbox.get_tools())] == ["notion-search"]


def test_toolbox_catalog_cache_expires_and_never_keeps_a_consent_prompt(monkeypatch):
    from savant.tools import notion_foundry

    listings, consent = [], [False]
    tool = StructuredTool.from_function(lambda: "ok", name="web_search", description="Search")
    prompt = StructuredTool.from_function(lambda: "sign in", name="oauth_consent_required", description="Consent")

    class Toolbox:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def get_tools(self):
            listings.append(1)
            return [prompt] if consent[0] else [tool]

        async def get_tools_requiring_approval(self):
            return []

    monkeypatch.setattr(notion_foundry, "EndpointToolbox", Toolbox)
    settings = Settings("https://model/", "model", toolbox_endpoint="https://x/api/projects/p/toolboxes/sa2-web/mcp")

    async def run():
        load = notion_foundry.toolbox_loader(settings)
        await load()
        await load()
        assert listings == [1]
        monkeypatch.setattr(notion_foundry, "TOOLBOX_CACHE_SECONDS", 0.0)
        load = notion_foundry.toolbox_loader(settings)
        consent[0] = True
        await load()
        await load()
        assert len(listings) == 3  # a consent prompt is listed again every time
        consent[0] = False
        await load()
        await load()
        assert len(listings) == 5  # expired immediately with a zero lifetime

    asyncio.run(run())
