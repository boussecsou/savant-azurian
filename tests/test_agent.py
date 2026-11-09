from savant.agent import build_model, build_server
from savant.config import Settings
from savant.tools import DEFAULT_TOOLS
from langchain_core.messages import AIMessage


class FakeModel:
    def invoke(self, messages):
        return AIMessage(content="minimal response")


def test_build_server_wraps_the_minimal_graph(monkeypatch):
    captured = {}

    class FakeResponsesHostServer:
        def __init__(self, graph):
            captured["graph"] = graph

    monkeypatch.setattr("savant.agent.ResponsesHostServer", FakeResponsesHostServer)
    settings = Settings("https://example.openai.azure.com/openai/v1/", "test-model")

    server = build_server(settings, model=FakeModel())

    assert isinstance(server, FakeResponsesHostServer)
    result = captured["graph"].invoke({"messages": ["Hello"]})
    assert result["messages"][-1].content == "minimal response"


def test_build_model_uses_default_azure_credential(monkeypatch):
    captured = {}

    class FakeCredential:
        pass

    class FakeChatModel:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def bind_tools(self, tools):
            captured["bound_tools"] = tools
            return self

    monkeypatch.setattr("savant.agent.DefaultAzureCredential", FakeCredential)
    monkeypatch.setattr("savant.agent.ChatOpenAI", FakeChatModel)
    monkeypatch.setattr(
        "savant.agent.get_bearer_token_provider",
        lambda credential, scope: (credential, scope),
    )

    model = build_model(
        Settings(
            "https://example.openai.azure.com/openai/v1/",
            "sa2-gpt-6-luna",
        )
    )

    assert isinstance(model, FakeChatModel)
    assert captured["base_url"] == "https://example.openai.azure.com/openai/v1/"
    assert captured["model"] == "sa2-gpt-6-luna"
    assert captured["use_responses_api"] is True
    assert captured["output_version"] == "responses/v1"
    assert captured["store"] is False
    assert captured["include"] == ["reasoning.encrypted_content"]
    credential, scope = captured["api_key"]
    assert isinstance(credential, FakeCredential)
    assert scope == "https://ai.azure.com/.default"
    assert captured["bound_tools"] == DEFAULT_TOOLS


def test_root_entry_point_exposes_the_agent_main_function():
    import main

    assert main.main.__module__ == "savant.agent"


def test_disabled_notion_does_not_discover_tools(monkeypatch):
    def unexpected_discovery(_settings):
        raise AssertionError("Disabled Notion must not connect.")

    monkeypatch.setattr("savant.tools.notion.load_notion_tools", unexpected_discovery)
    monkeypatch.setattr("savant.agent.ResponsesHostServer", lambda graph: graph)
    graph = build_server(
        Settings("https://model.example/openai/v1/", "model"), FakeModel()
    )
    assert graph.checkpointer is None


def test_enabled_notion_binds_discovered_tools_and_enables_checkpointing(monkeypatch):
    from langchain_core.tools import tool

    @tool
    def fetch(page_id: str) -> str:
        """Read a Notion page."""
        return "page content"

    captured = {}
    monkeypatch.setattr("savant.tools.notion.load_notion_tools", lambda _: [fetch])
    monkeypatch.setattr("savant.agent.ResponsesHostServer", lambda graph: graph)

    def fake_build_model(settings, tools):
        captured["tools"] = tools
        return FakeModel()

    monkeypatch.setattr("savant.agent.build_model", fake_build_model)
    graph = build_server(Settings(
        "https://model.example/openai/v1/", "model",
        notion_mcp_enabled=True, notion_read_tool_names=("fetch",),
    ))
    assert captured["tools"] == [*DEFAULT_TOOLS, fetch]
    assert graph.checkpointer is not None


def test_model_probe_client_does_not_bind_tools(monkeypatch):
    class Model:
        def __init__(self, **kwargs):
            pass
        def bind_tools(self, tools):
            raise AssertionError("The runtime probe must not advertise tools")
    monkeypatch.setattr("savant.agent.ChatOpenAI", Model)
    monkeypatch.setattr("savant.agent.DefaultAzureCredential", lambda: object())
    monkeypatch.setattr("savant.agent.get_bearer_token_provider", lambda *args: "test-token")
    assert isinstance(build_model(Settings("https://model/", "model"), ()), Model)


def test_chat_oauth_server_does_not_authenticate_or_discover_at_boot(monkeypatch, tmp_path):
    from cryptography.fernet import Fernet
    from types import SimpleNamespace
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        yield

    class Host:
        def __init__(self, graph):
            self.graph = graph
            self.app = SimpleNamespace(router=SimpleNamespace(lifespan_context=lifespan))

    monkeypatch.setattr("savant.semantic_approval.ConversationalResponsesHostServer", Host)
    monkeypatch.setenv("NOTION_OAUTH_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr("savant.notion_oauth.NotionOAuth.begin", lambda *args: (_ for _ in ()).throw(AssertionError("No OAuth at boot")))
    monkeypatch.setattr("savant.notion_oauth.NotionOAuth.get_access_token", lambda *args: (_ for _ in ()).throw(AssertionError("No token lookup at boot")))
    monkeypatch.setattr("savant.tools.notion_chat.discover_tools", lambda *args: (_ for _ in ()).throw(AssertionError("No discovery at boot")))
    server = build_server(Settings("https://model/", "model", notion_mcp_enabled=True,
                                  notion_oauth_callback_url="http://localhost:8090/oauth/notion/callback",
                                  notion_oauth_store_url="sqlite://" + str(tmp_path / "oauth.db")))
    assert server.graph.checkpointer is not None
