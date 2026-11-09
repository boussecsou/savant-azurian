"""Local connection to Notion's hosted MCP server."""

from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv
from fastmcp import Client
from fastmcp.client.auth import OAuth
from langchain.mcp import MCPAdapter
from langchain_core.tools import BaseTool

from ..config import Settings

logger = logging.getLogger(__name__)


def build_notion_client(url: str) -> Client:
    """Use Notion's supported public-client registration with PKCE.

    Requesting `none` avoids the MCP SDK's Basic-auth interoperability bug:
    it otherwise duplicates client_id in the Authorization header and form.
    OAuth still requires browser consent and a PKCE code verifier.
    """

    oauth = OAuth(
        url,
        client_name="Savant Azurian 2",
        additional_client_metadata={"token_endpoint_auth_method": "none"},
    )
    return Client(url, auth=oauth)


async def discover_notion_tools(settings: Settings) -> list[BaseTool]:
    """Authenticate, discover tools, and return only the configured allowlists."""

    client = build_notion_client(settings.notion_mcp_url)
    adapter = MCPAdapter(client)
    tools = await adapter.list_tools(cache_mode="bypass")
    tools_by_name = {tool.name: tool for tool in tools}
    available_names = sorted(tools_by_name)
    requested_names = (
        *settings.notion_read_tool_names,
        *settings.notion_write_tool_names,
    )
    missing_names = sorted(set(requested_names) - tools_by_name.keys())
    if missing_names:
        raise RuntimeError(
            "Configured Notion MCP tools are not offered by the server: "
            f"{', '.join(missing_names)}. Available tools: "
            f"{', '.join(available_names)}"
        )

    if not settings.notion_read_tool_names:
        raise RuntimeError(
            "No Notion read allowlist is configured. Available tools: "
            f"{', '.join(available_names)}. Set NOTION_READ_TOOL_NAMES and restart."
        )

    selected = [tools_by_name[name] for name in requested_names]
    logger.info("Enabled Notion MCP tools: %s", ", ".join(tool.name for tool in selected))
    return selected


def load_notion_tools(settings: Settings) -> list[BaseTool]:
    """Run OAuth discovery from the synchronous local/hosted startup entrypoint."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(discover_notion_tools(settings))
    raise RuntimeError(
        "Notion MCP discovery cannot run inside an existing event loop; "
        "initialize the agent from a synchronous entry point."
    )


def main() -> None:
    """Authenticate and show available Notion tool names."""

    from ..config import NOTION_MCP_DEFAULT_URL

    load_dotenv(override=False)
    url = os.environ.get("NOTION_MCP_URL", NOTION_MCP_DEFAULT_URL).strip()
    for name in asyncio.run(_list_tool_names(url)):
        print(name)


async def _list_tool_names(url: str) -> list[str]:
    adapter = MCPAdapter(build_notion_client(url))
    tools = await adapter.list_tools(cache_mode="bypass")
    return sorted(tool.name for tool in tools)


if __name__ == "__main__":
    main()
