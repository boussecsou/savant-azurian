"""Configuration and model wiring for the isolated approval classifier."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from savant.agent import build_model, build_server
from savant.config import Settings


def set_minimal_env(monkeypatch):
    monkeypatch.setattr("savant.config.load_dotenv", lambda **_: None)
    monkeypatch.setenv("AZURE_OPENAI_BASE_URL", "https://model.example/openai/v1")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "chat-model")


@pytest.mark.parametrize("value", ["not-a-number", "0", "-1", "30.1", "nan", "inf"])
def test_settings_reject_invalid_semantic_approval_timeout(monkeypatch, value):
    set_minimal_env(monkeypatch)
    monkeypatch.setenv("SEMANTIC_APPROVAL_TIMEOUT", value)
    with pytest.raises(RuntimeError, match="SEMANTIC_APPROVAL_TIMEOUT"):
        Settings.from_env()


def test_settings_reads_approval_model_override_and_timeout(monkeypatch):
    set_minimal_env(monkeypatch)
    monkeypatch.setenv("SEMANTIC_APPROVAL_MODEL", "separate-approval-model")
    monkeypatch.setenv("SEMANTIC_APPROVAL_TIMEOUT", "4.5")
    settings = Settings.from_env()
    assert settings.semantic_approval_model == "separate-approval-model"
    assert settings.semantic_approval_timeout == 4.5


def test_identity_diagnostics_are_opt_in(monkeypatch):
    set_minimal_env(monkeypatch)
    monkeypatch.delenv("NOTION_IDENTITY_DIAGNOSTICS", raising=False)
    settings = Settings.from_env()
    assert settings.notion_identity_diagnostics is False

    monkeypatch.setenv("NOTION_IDENTITY_DIAGNOSTICS", "true")
    assert Settings.from_env().notion_identity_diagnostics is True


def test_build_model_uses_separate_tool_free_classifier_configuration(monkeypatch):
    captured = {}

    class FakeChatModel:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def bind_tools(self, tools):
            raise AssertionError("The semantic approval classifier must not receive tools")

    monkeypatch.setattr("savant.agent.DefaultAzureCredential", lambda: object())
    monkeypatch.setattr("savant.agent.get_bearer_token_provider", lambda *args: "fake-token")
    monkeypatch.setattr("savant.agent.ChatOpenAI", FakeChatModel)
    settings = Settings(
        "https://model.example/openai/v1/",
        "chat-model",
        semantic_approval_model="approval-model",
        semantic_approval_timeout=4.5,
    )

    model = build_model(settings, (), guardrail=True)

    assert isinstance(model, FakeChatModel)
    assert captured["model"] == "approval-model"
    assert captured["base_url"] == settings.azure_openai_base_url
    assert captured["timeout"] == 4.5
    # One retry for a rate limit; no reasoning (measured steadier on GPT-6 Luna, issue #50).
    assert captured["max_retries"] == 1
    assert captured["max_tokens"] == 256
    assert captured["reasoning_effort"] == "none"


def test_build_server_wires_classifier_model_and_configured_timeout(monkeypatch):
    captured = {}

    class FakeOAuth:
        store = object()

    class FakeGuardrail:
        def __init__(self, model, *, timeout):
            captured["guardrail_model"] = model
            captured["guardrail_timeout"] = timeout

    class FakeHost:
        def __init__(self, graph):
            captured["graph"] = graph

            @asynccontextmanager
            async def lifespan_context(app):
                yield

            self.app = SimpleNamespace(router=SimpleNamespace(lifespan_context=lifespan_context))

    approval_model = object()

    def fake_build_model(settings, tools=(), *, guardrail=False, token_provider=None):
        captured["model_args"] = (settings, tools, guardrail)
        return approval_model

    monkeypatch.setattr("savant.oauth_runtime.build_oauth_service", lambda *args, **kwargs: FakeOAuth())
    monkeypatch.setattr("savant.semantic_approval.SemanticApprovalGuardrail", FakeGuardrail)
    monkeypatch.setattr("savant.semantic_approval.ConversationalResponsesHostServer", FakeHost)
    monkeypatch.setattr("savant.agent.build_model", fake_build_model)
    monkeypatch.setattr(
        "savant.tools.notion_chat.build_direct_chat_graph",
        lambda *args, **kwargs: captured.update(graph_kwargs=kwargs) or "fake-graph",
    )

    settings = Settings(
        "https://model.example/openai/v1/",
        "chat-model",
        notion_mcp_enabled=True,
        notion_oauth_callback_url="https://callback.example/oauth/notion/callback",
        notion_oauth_store_url="https://storage.example/oauth.enc",
        semantic_approval_model="approval-model",
        semantic_approval_timeout=6.25,
    )
    server = build_server(settings)

    assert isinstance(server, FakeHost)
    assert captured["model_args"] == (settings, (), True)
    assert captured["guardrail_model"] is approval_model
    assert captured["guardrail_timeout"] == 6.25
    assert captured["graph_kwargs"]["guardrail"].__class__ is FakeGuardrail


def _captured_main_model(monkeypatch, settings):
    captured = {}

    class FakeChatModel:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def bind_tools(self, tools):
            return self

    monkeypatch.setattr("savant.agent.DefaultAzureCredential", lambda: object())
    monkeypatch.setattr("savant.agent.get_bearer_token_provider", lambda *args: "fake-token")
    monkeypatch.setattr("savant.agent.ChatOpenAI", FakeChatModel)
    build_model(settings, ())
    return captured


def test_main_model_uses_low_reasoning_effort_by_default(monkeypatch):
    captured = _captured_main_model(monkeypatch, Settings("https://model.example/openai/v1/", "chat-model"))
    assert captured["reasoning_effort"] == "low"
    # The classifier-only limits must not leak onto the chat model, which has its own bounds.
    assert "max_tokens" not in captured
    assert captured["timeout"] == 90.0 and captured["max_retries"] == 2


def test_main_model_keeps_the_provider_default_when_effort_is_empty(monkeypatch):
    settings = Settings("https://model.example/openai/v1/", "chat-model", model_reasoning_effort="")
    assert "reasoning_effort" not in _captured_main_model(monkeypatch, settings)


def test_reasoning_effort_is_read_from_the_environment_and_validated(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_BASE_URL", "https://model.example/openai/v1/")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "chat-model")
    monkeypatch.delenv("MODEL_REASONING_EFFORT", raising=False)
    assert Settings.from_env().model_reasoning_effort == "low"
    monkeypatch.setenv("MODEL_REASONING_EFFORT", " Medium ")
    assert Settings.from_env().model_reasoning_effort == "medium"
    monkeypatch.setenv("MODEL_REASONING_EFFORT", "")
    assert Settings.from_env().model_reasoning_effort == ""
    monkeypatch.setenv("MODEL_REASONING_EFFORT", "turbo")
    with pytest.raises(RuntimeError, match="MODEL_REASONING_EFFORT"):
        Settings.from_env()
