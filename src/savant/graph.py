"""The minimal Savant LangGraph: input messages -> model -> response."""

from __future__ import annotations

from typing import Any, Protocol, Sequence

from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import MessagesState, StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.prebuilt import ToolNode, tools_condition

from .identity import BASE_IDENTITY, current_time_context
from .tools import DEFAULT_TOOLS
from .tools.approval import approval_hooks


class ChatModel(Protocol):
    """Small interface that keeps the graph independent from Foundry wiring."""

    def invoke(self, input: list[Any]) -> Any:
        """Return a model message for the supplied conversation."""


def build_graph(
    model: ChatModel,
    tools: Sequence[BaseTool] = DEFAULT_TOOLS,
    checkpointer: BaseCheckpointSaver | None = None,
    approval_tool_names: Sequence[str] = (),
):
    """Compile the Savant graph: model decides between a direct response and a tool call.

    The model is expected to already be bound to `tools` (see `agent.build_model`) so
    that it can emit native `AIMessage.tool_calls`. `tools_condition` routes to the
    `tools` node when present, and to `END` otherwise; `ToolNode` itself returns an
    error `ToolMessage` for a tool name it doesn't recognize instead of raising.
    """

    def call_model(state: MessagesState) -> dict[str, list[Any]]:
        # The identity is injected here, transiently, for each model call -- it
        # is never appended to `state["messages"]`, so it can't pile up across
        # the tool-call loop back to this node.
        messages = [SystemMessage(content=BASE_IDENTITY + current_time_context()), *state["messages"]]
        return {"messages": [model.invoke(messages)]}

    if approval_tool_names and checkpointer is None:
        raise ValueError("Tool approvals require a checkpointer.")
    sync_approval, async_approval = approval_hooks(approval_tool_names)

    workflow = StateGraph(MessagesState)
    workflow.add_node("model", call_model)
    workflow.add_node(
        "tools",
        ToolNode(tools, wrap_tool_call=sync_approval, awrap_tool_call=async_approval),
    )
    workflow.set_entry_point("model")
    workflow.add_conditional_edges("model", tools_condition)
    workflow.add_edge("tools", "model")
    return workflow.compile(checkpointer=checkpointer)
