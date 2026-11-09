"""Pause write tool calls before delegating to LangGraph's native ToolNode."""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import (
    AsyncToolCallWrapper,
    ToolCallRequest,
    ToolCallWrapper,
)
from langgraph.types import interrupt


def approval_hooks(
    tool_names: Sequence[str],
) -> tuple[ToolCallWrapper, AsyncToolCallWrapper]:
    """Build sync and async gates without altering tool schemas or MCP results."""

    protected_names = frozenset(tool_names)

    def rejection(request: ToolCallRequest) -> ToolMessage | None:
        call = request.tool_call
        if call["name"] not in protected_names or request.tool is None:
            return None

        approval_request = {
            "kind": "notion_write_approval",
            "tool_name": call["name"],
            "tool_call_id": call["id"],
            "arguments": call["args"],
        }
        # ResponsesHostServer echoes this exact value when the matching
        # mcp_approval_response approves the call. Other resume values decline it.
        decision = interrupt(approval_request)
        if decision == approval_request:
            return None
        return ToolMessage(
            content="The Notion write was rejected; no change was made.",
            name=call["name"],
            tool_call_id=call["id"],
            status="error",
        )

    def sync_gate(request, execute):
        declined = rejection(request)
        return declined if declined is not None else execute(request)

    async def async_gate(request, execute):
        declined = rejection(request)
        return declined if declined is not None else await execute(request)

    return sync_gate, async_gate
