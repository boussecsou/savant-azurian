import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from savant.graph import build_graph
from savant.identity import BASE_IDENTITY


class FakeModel:
    """Returns one canned response per call, in order, recording what it was called with."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return self._responses.pop(0)


def test_graph_returns_a_direct_response_when_the_model_calls_no_tool():
    graph = build_graph(FakeModel([AIMessage(content="Bonjour !")]))

    result = graph.invoke({"messages": [HumanMessage(content="Bonjour Savant")]})

    assert result["messages"][-1].content == "Bonjour !"


def test_graph_injects_the_base_identity_without_persisting_it_in_state():
    model = FakeModel([AIMessage(content="Bonjour !")])
    graph = build_graph(model)

    result = graph.invoke({"messages": [HumanMessage(content="Bonjour Savant")]})

    sent_messages = model.calls[0]
    assert isinstance(sent_messages[0], SystemMessage)
    assert sent_messages[0].content.startswith(BASE_IDENTITY)
    assert "Current date and time (Africa/Casablanca):" in sent_messages[0].content
    assert not any(isinstance(m, SystemMessage) for m in result["messages"])


def test_graph_executes_a_tool_call_and_returns_the_models_follow_up():
    tool_call = {"name": "echo", "args": {"text": "ping"}, "id": "call_1"}
    graph = build_graph(
        FakeModel(
            [
                AIMessage(content="", tool_calls=[tool_call]),
                AIMessage(content="Le tool a renvoyé: ping"),
            ]
        )
    )

    result = graph.invoke({"messages": [HumanMessage(content="echo ping")]})

    tool_message = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert tool_message.content == "ping"
    assert tool_message.tool_call_id == "call_1"
    assert result["messages"][-1].content == "Le tool a renvoyé: ping"


def test_graph_reports_an_invalid_tool_name_without_crashing():
    tool_call = {"name": "does_not_exist", "args": {}, "id": "call_2"}
    graph = build_graph(
        FakeModel(
            [
                AIMessage(content="", tool_calls=[tool_call]),
                AIMessage(content="Je ne peux pas utiliser cet outil."),
            ]
        )
    )

    result = graph.invoke({"messages": [HumanMessage(content="appelle un outil qui n'existe pas")]})

    tool_message = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert tool_message.status == "error"
    assert result["messages"][-1].content == "Je ne peux pas utiliser cet outil."


@pytest.mark.parametrize("approved", [True, False])
def test_notion_write_waits_for_approval_and_can_target_any_page(approved):
    calls = []

    def fake_write(page_id: str, title: str):
        calls.append({"page_id": page_id, "title": title})
        return "updated", {"page_id": page_id}

    write_tool = StructuredTool.from_function(
        func=fake_write,
        name="update_page",
        description="Update a Notion page.",
        response_format="content_and_artifact",
    )
    arguments = {"page_id": "any-authorized-page", "title": "Local test"}
    graph = build_graph(
        FakeModel(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "update_page",
                            "args": arguments,
                            "id": "write_1",
                        }
                    ],
                ),
                AIMessage(content="Terminé."),
            ]
        ),
        tools=[write_tool],
        checkpointer=MemorySaver(),
        approval_tool_names=("update_page",),
    )
    config = {"configurable": {"thread_id": "notion-write-test"}}

    graph.invoke({"messages": [HumanMessage(content="Modifie cette page.")]}, config)
    assert calls == []
    pending = graph.get_state(config).tasks[0].interrupts[0]
    assert pending.value["arguments"] == arguments
    assert pending.value["tool_call_id"] == "write_1"
    decision = pending.value if approved else {"approved": False}

    result = graph.invoke(Command(resume=decision), config)
    message = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    if approved:
        assert calls == [arguments]
        assert message.content == "updated"
        assert message.artifact == {"page_id": "any-authorized-page"}
        assert message.status == "success"
    else:
        assert calls == []
        assert message.status == "error"
        assert "rejected" in message.content


def test_notion_read_does_not_need_approval():
    read_tool = StructuredTool.from_function(
        func=lambda page_id: "page content",
        name="fetch",
        description="Read a Notion page.",
    )
    graph = build_graph(
        FakeModel(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "fetch",
                            "args": {"page_id": "page"},
                            "id": "read_1",
                        }
                    ],
                ),
                AIMessage(content="Voici la page."),
            ]
        ),
        tools=[read_tool],
        checkpointer=MemorySaver(),
        approval_tool_names=("update_page",),
    )
    result = graph.invoke(
        {"messages": [HumanMessage(content="Lis cette page.")]},
        {"configurable": {"thread_id": "notion-read-test"}},
    )
    assert result["messages"][-1].content == "Voici la page."
    assert "__interrupt__" not in result


def test_write_approvals_require_a_checkpointer():
    with pytest.raises(ValueError, match="require a checkpointer"):
        build_graph(FakeModel([]), approval_tool_names=("update_page",))
