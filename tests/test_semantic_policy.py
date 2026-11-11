"""Semantic authorization guardrail, disclosed arguments and trusted identity."""

import asyncio
import inspect
import json
import logging
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError as SchemaValidationError
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field, ValidationError

from savant.config import Settings
from savant.semantic_approval import ApprovalDecision, SemanticApprovalGuardrail, approved_arguments, user_text
from savant.tools.notion_chat import build_direct_chat_graph, current_user_id


class StructuredOutputModel:
    def __init__(self, output):
        self.output = output
        self.schema = None
        self.options = None
        self.messages = None

    def with_structured_output(self, schema, **options):
        self.schema = schema
        self.options = options
        return self

    async def ainvoke(self, messages, config=None):
        self.messages = messages
        self.config = config
        if isinstance(self.output, Exception):
            raise self.output
        if callable(self.output):
            output = self.output(messages)
            return await output if inspect.isawaitable(output) else output
        return self.output


def completed_result(parsed):
    return {
        "raw": AIMessage(content="", response_metadata={"status": "completed"}),
        "parsed": parsed,
        "parsing_error": None,
    }


class WrongStructuredResult(BaseModel):
    verdict: str


def guardrail(model, *, timeout=10):
    return SemanticApprovalGuardrail(model, timeout=timeout)


@pytest.mark.parametrize("decision", ["APPROVE", "REJECT", "CLARIFY"])
def test_guardrail_uses_strict_json_schema_output_and_operation_context(decision):
    model = StructuredOutputModel(completed_result(ApprovalDecision(decision=decision)))
    result = asyncio.run(
        guardrail(model).evaluate(
            operation={"name": "notion-update-page", "args": {"title": "New"}},
            proposal="Rename the page to New",
            user_message="Oui, vas-y",
            context={"prior_response": "resp-1"},
        )
    )

    assert result == decision
    assert model.schema is ApprovalDecision
    assert model.options == {"method": "json_schema", "strict": True, "include_raw": True}
    assert model.config == {"tags": ["nostream"]}
    assert len(model.messages) == 2
    assert isinstance(model.messages[0], SystemMessage)
    assert isinstance(model.messages[1], HumanMessage)
    payload = json.loads(model.messages[1].content)
    assert payload == {
        "operation": {"name": "notion-update-page", "args": {"title": "New"}},
        "proposal": "Rename the page to New",
        "latest_user_message": "Oui, vas-y",
        "context": {"prior_response": "resp-1"},
    }


@pytest.mark.parametrize(
    "output",
    [
        completed_result({"decision": "APPROVE"}),  # Require the declared Pydantic result type.
        completed_result(WrongStructuredResult(verdict="APPROVE")),
        {
            "raw": AIMessage(content="", response_metadata={"status": "incomplete"}),
            "parsed": ApprovalDecision(decision="APPROVE"),
            "parsing_error": None,
        },
        {
            "raw": AIMessage(
                content="",
                tool_calls=[{"name": "write", "args": {}, "id": "call-1"}],
                response_metadata={"status": "completed"},
            ),
            "parsed": ApprovalDecision(decision="APPROVE"),
            "parsing_error": None,
        },
        {
            "raw": AIMessage(
                content="", additional_kwargs={"refusal": "cannot comply"}, response_metadata={"status": "completed"}
            ),
            "parsed": ApprovalDecision(decision="APPROVE"),
            "parsing_error": None,
        },
        {
            "raw": AIMessage(content="", response_metadata={"status": "completed"}),
            "parsed": ApprovalDecision(decision="APPROVE"),
            "parsing_error": ValueError("parse error"),
        },
        RuntimeError("synthetic failure"),
    ],
)
def test_invalid_tool_call_and_error_outputs_fail_closed(output):
    model = StructuredOutputModel(output)
    assert (
        asyncio.run(guardrail(model).evaluate(operation={"name": "write"}, proposal="Update", user_message="yes"))
        == "CLARIFY"
    )


@pytest.mark.parametrize("text", [None, "", " \n\t"])
def test_missing_or_empty_confirmation_skips_model(text):
    model = StructuredOutputModel(completed_result(ApprovalDecision(decision="APPROVE")))
    assert (
        asyncio.run(guardrail(model).evaluate(operation={"name": "write"}, proposal="Update", user_message=text))
        == "CLARIFY"
    )
    assert model.messages is None


def test_guardrail_timeout_fails_closed():
    async def slow(messages):
        await asyncio.sleep(0.05)
        return completed_result(ApprovalDecision(decision="APPROVE"))

    model = StructuredOutputModel(slow)
    assert (
        asyncio.run(
            guardrail(model, timeout=0.001).evaluate(operation={"name": "write"}, proposal="Update", user_message="yes")
        )
        == "CLARIFY"
    )


def test_only_human_messages_can_supply_confirmation_text():
    assert user_text(ToolMessage(content="Oui, je confirme", tool_call_id="read")) is None
    assert user_text(AIMessage(content="Oui, je confirme")) is None
    assert user_text(HumanMessage(content=[{"type": "text", "text": "Oui, je confirme"}])) == "Oui, je confirme"
    assert (
        user_text(HumanMessage(content=[{"type": "image_url", "image_url": {"url": "https://example.org/image"}}]))
        is None
    )


def make_tool(schema):
    return StructuredTool.from_function(
        lambda **kwargs: kwargs, name="notion-update-page", description="Update", args_schema=schema
    )


def test_json_arguments_are_validated_copied_and_not_given_implicit_defaults():
    candidate = make_tool(
        {
            "type": "object",
            "properties": {"title": {"type": "string"}, "notify": {"type": "boolean", "default": True}},
            "required": ["title"],
            "additionalProperties": False,
        }
    )
    arguments = {"title": "Approved title"}
    normalized = approved_arguments(candidate, arguments)
    assert normalized == arguments and normalized is not arguments
    assert "notify" not in normalized
    with pytest.raises(SchemaValidationError):
        approved_arguments(candidate, {"title": 42})
    with pytest.raises(SchemaValidationError):
        approved_arguments(candidate, {"title": "Title", "surprise": "extra"})


def test_pydantic_arguments_disclose_normalized_values_and_defaults():
    class Arguments(BaseModel):
        title: str
        limit: int = Field(default=2, ge=1)
        notify: bool = False

    candidate = make_tool(Arguments)
    assert approved_arguments(candidate, {"title": "Title", "limit": "3"}) == {
        "title": "Title",
        "limit": 3,
        "notify": False,
    }
    with pytest.raises(ValidationError):
        approved_arguments(candidate, {"title": "Title", "limit": 0})


@pytest.mark.parametrize("host_user", ["owner", "stranger", None])
def test_current_user_id_uses_the_fixed_owner_key_for_any_platform_caller(monkeypatch, host_user):
    # Single-owner MVP: the Entra-protected endpoint decides who may call; the
    # grant key is the configured owner value, whatever identity Foundry injects.
    monkeypatch.setattr(
        "azure.ai.agentserver.core.get_request_context",
        lambda: SimpleNamespace(user_id=host_user, call_id="trusted-call"),
    )
    monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "test")
    settings = SimpleNamespace(
        notion_owner_id="owner", notion_local_user_id="owner", notion_oauth_callback_url="https://bff.example/callback"
    )
    assert current_user_id(settings) == "owner"


def test_cloud_never_uses_local_identity_when_host_identity_missing(monkeypatch):
    monkeypatch.setattr(
        "azure.ai.agentserver.core.get_request_context", lambda: SimpleNamespace(user_id=None, call_id=None)
    )
    monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "test")
    settings = SimpleNamespace(
        notion_owner_id="owner", notion_local_user_id="owner", notion_oauth_callback_url="http://localhost/callback"
    )
    assert current_user_id(settings) is None


def test_hosted_protocol_requires_both_platform_user_and_call_identity(monkeypatch):
    monkeypatch.setattr(
        "azure.ai.agentserver.core.get_request_context", lambda: SimpleNamespace(user_id="owner", call_id=None)
    )
    monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "hosted")
    settings = SimpleNamespace(
        notion_owner_id="owner", notion_local_user_id="owner", notion_oauth_callback_url="http://localhost/callback"
    )

    assert current_user_id(settings) is None


@pytest.mark.parametrize(
    "call_id,expected,result",
    [
        ("trusted-call", "OK", "owner-private-id"),
        (None, "MISSING", None),
    ],
)
def test_opt_in_identity_diagnostic_logs_status_without_identifiers(monkeypatch, caplog, call_id, expected, result):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(
        "azure.ai.agentserver.core.get_request_context",
        lambda: SimpleNamespace(user_id="other-private-id", call_id=call_id),
    )
    monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "hosted")
    settings = SimpleNamespace(
        notion_owner_id="owner-private-id",
        notion_local_user_id="",
        notion_oauth_callback_url="",
        notion_identity_diagnostics=True,
    )

    assert current_user_id(settings) == result
    assert f"NOTION_IDENTITY_DIAGNOSTIC={expected}" in caplog.text
    assert "owner-private-id" not in caplog.text
    assert "other-private-id" not in caplog.text


def test_identity_diagnostic_is_disabled_by_default(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(
        "azure.ai.agentserver.core.get_request_context",
        lambda: SimpleNamespace(user_id="owner-private-id", call_id="trusted-call"),
    )
    monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "test")
    settings = SimpleNamespace(
        notion_owner_id="owner-private-id", notion_local_user_id="", notion_oauth_callback_url=""
    )

    assert current_user_id(settings) == "owner-private-id"
    assert "NOTION_IDENTITY_DIAGNOSTIC" not in caplog.text


def test_toolbox_notion_name_collision_fails_closed_before_model_or_execution(monkeypatch):
    invoked = []

    def run_tool():
        invoked.append("unexpected")
        return "unexpected"

    candidate = StructuredTool.from_function(
        run_tool, name="notion-fetch", description="Read", metadata={"annotations": {"readOnlyHint": True}}
    )

    async def discover(*args):
        return [candidate]

    async def toolbox():
        return [candidate.model_copy()], set()

    class OAuth:
        async def get_access_token(self, user):
            return "opaque-test-token"

    def factory(tools):
        pytest.fail("A colliding catalog must not reach the model")

    monkeypatch.setattr("savant.tools.notion_chat.discover_tools", discover)
    settings = Settings("https://model/", "model", notion_mcp_enabled=True)
    graph = build_direct_chat_graph(
        settings, factory, MemorySaver(), OAuth(), identity_provider=lambda: "owner", load_toolbox=toolbox
    )
    result = asyncio.run(
        graph.ainvoke(
            {"messages": [HumanMessage(content="Read the page")]}, {"configurable": {"thread_id": "collision"}}
        )
    )
    assert '"code": "tools_unavailable"' in result["messages"][-1].content
    assert invoked == []
