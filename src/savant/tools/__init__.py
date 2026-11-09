"""Tools available to the Savant model."""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool


@tool
def echo(text: str) -> str:
    """Echo the given text back unchanged."""

    return text


DEFAULT_TOOLS: list[BaseTool] = [echo]
