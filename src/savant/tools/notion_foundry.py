"""Request-scoped tools through the official Foundry toolbox client."""

import asyncio
import time

from langchain_azure_ai.tools import AzureAIProjectToolbox
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph import MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from ..health import is_runtime_probe
from ..identity import BASE_IDENTITY, current_time_context
from . import DEFAULT_TOOLS
from .approval import approval_hooks


class EndpointToolbox(AzureAIProjectToolbox):
    """Use a consumer or version URL with the installed SDK's auth/context handling."""

    mcp_endpoint: str

    @property
    def toolbox_endpoint(self) -> str:
        return self.mcp_endpoint

    def _build_mcp_client(self):
        """Bridge the SDK to MCP 2 using the same adapter as the direct backend.

        The SDK's legacy langchain-mcp-adapters transport requires MCP 1;
        langchain[mcp] requires MCP 2. Keep SDK auth, caller headers and consent
        handling while using the supported MCP 2 transport.
        """
        import httpx2
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport
        from langchain.mcp import MCPAdapter

        auth, headers = self._build_auth_and_headers()

        class Auth(httpx2.Auth):
            def auth_flow(self, request):
                yield from auth.auth_flow(request)

        endpoint = self.toolbox_endpoint

        class MCPClient:
            async def get_tools(self):
                # The toolbox answers server/discover at 2026-07-28 but omits
                # that revision's required tools/list fields (resultType,
                # ttlMs, cacheScope); force the initialize handshake.
                client = Client(
                    StreamableHttpTransport(endpoint, headers=headers, auth=Auth()),
                    mode="legacy",
                )
                return await MCPAdapter(client).list_tools(cache_mode="bypass")

        return MCPClient()


# The toolbox catalog (names, schemas, approval flags) changes only when the toolbox is edited, but
# listing it costs ~7 s (MCP handshake, tools/list, approval metadata, a token per call). Tool calls
# still stamp the per-request Foundry call ID: the SDK reads it from the request context at send time.
TOOLBOX_CACHE_SECONDS = 600.0


def toolbox_loader(settings, credential=None):
    """Build a loader reusable alongside direct Notion tools, cached for TOOLBOX_CACHE_SECONDS.

    `credential` is shared with the model client so the managed identity token is fetched once
    and reused, instead of a new DefaultAzureCredential (and token request) on every load.
    """
    shared = {"credential": credential} if credential is not None else {}
    toolbox = (
        EndpointToolbox(
            project_endpoint=settings.foundry_project_endpoint,
            toolbox_name=settings.toolbox_endpoint.split("/toolboxes/")[1].split("/")[0],
            mcp_endpoint=settings.toolbox_endpoint,
            **shared,
        )
        if settings.toolbox_endpoint
        else AzureAIProjectToolbox(
            project_endpoint=settings.foundry_project_endpoint,
            toolbox_name=settings.notion_toolbox_name,
            **shared,
        )
    )
    cache = {"until": 0.0, "value": None}
    lock = asyncio.Lock()

    async def load_tools():
        if cache["value"] is not None and time.monotonic() < cache["until"]:
            return cache["value"]
        async with lock:
            if cache["value"] is not None and time.monotonic() < cache["until"]:
                return cache["value"]
            value = await discover()
            # A consent prompt is a state of the connection, not a catalog: never keep it.
            if not (len(value[0]) == 1 and value[0][0].name == "oauth_consent_required"):
                cache.update(value=value, until=time.monotonic() + TOOLBOX_CACHE_SECONDS)
            return value

    async def discover():
        async def approvals():
            return await toolbox.get_tools_requiring_approval()

        # Both read the same catalog: ask side by side. A consent prompt makes the approval list
        # irrelevant (and possibly failing), so its outcome only matters for a real catalog.
        discovered, platform_approvals = await asyncio.gather(toolbox.get_tools(), approvals(), return_exceptions=True)
        if isinstance(discovered, BaseException):
            raise discovered
        # The SDK returns a synthetic tool when discovery needs OAuth consent.
        if len(discovered) == 1 and discovered[0].name == "oauth_consent_required":
            return discovered, ()
        if isinstance(platform_approvals, BaseException):
            raise platform_approvals
        requested = (*settings.notion_read_tool_names, *settings.notion_write_tool_names)
        by_name = {tool.name: tool for tool in discovered}
        if not settings.toolbox_endpoint and (not settings.notion_read_tool_names or set(requested) - by_name.keys()):
            raise RuntimeError(
                "Configure exact Notion toolbox tool names (including server prefixes). "
                f"Available names: {', '.join(sorted(by_name))}"
            )
        selected = [
            *DEFAULT_TOOLS,
            *(discovered if settings.toolbox_endpoint else [by_name[name] for name in requested]),
        ]
        if len({tool.name for tool in selected}) != len(selected):
            raise RuntimeError("Tool names must be unique across built-in and toolbox tools.")
        protected = set(settings.notion_write_tool_names) | ({tool.name for tool in selected} & set(platform_approvals))
        return selected, protected

    return load_tools


def build_foundry_graph(settings, model_factory, checkpointer):
    """Discover within the host request context; never cache caller-bound tools."""
    load_tools = toolbox_loader(settings)

    async def call_model(state):
        # A CD identity has no personal OAuth grant. Probe the real model
        # without discovering tools; ordinary requests still require consent.
        if is_runtime_probe(state["messages"]):
            response = await model_factory(()).ainvoke([SystemMessage(content=BASE_IDENTITY), *state["messages"]])
            return {"messages": [response]}
        tools, _ = await load_tools()
        if len(tools) == 1 and tools[0].name == "oauth_consent_required":
            instructions = await tools[0].ainvoke({"query": ""})
            # Discovery is retried on the next request; no restart is needed.
            instructions = instructions.replace("then restart the agent", "then send your request again")
            return {"messages": [AIMessage(content=instructions)]}
        model = model_factory(tools)
        response = await model.ainvoke(
            [SystemMessage(content=BASE_IDENTITY + current_time_context()), *state["messages"]]
        )
        return {"messages": [response]}

    async def call_tools(state, config):
        tools, protected = await load_tools()
        sync_gate, async_gate = approval_hooks(protected)
        return await ToolNode(tools, wrap_tool_call=sync_gate, awrap_tool_call=async_gate).ainvoke(state, config)

    workflow = StateGraph(MessagesState)
    workflow.add_node("model", call_model)
    workflow.add_node("tools", call_tools)
    workflow.set_entry_point("model")
    workflow.add_conditional_edges("model", tools_condition)
    workflow.add_edge("tools", "model")
    return workflow.compile(checkpointer=checkpointer)
