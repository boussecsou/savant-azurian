"""Timeouts, bounded retries and the tool-loop guard, through the chat graph (all simulated)."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver

from savant import reliability
from savant.config import Settings
from savant.notion_oauth import SQLiteOAuthStore
from savant.tools import notion_chat
from semantic_fakes import simulated_guardrail


class Harness:
    def __init__(self, tmp_path, monkeypatch, behaviour):
        self.calls, self.outputs, self.counter = 0, [], 0
        self.behaviour = behaviour
        monkeypatch.setattr(reliability, "TOOL_TIMEOUT_SECONDS", 0.2)
        monkeypatch.setattr(reliability, "RETRY_DELAY_SECONDS", 0.01)
        monkeypatch.setattr(notion_chat, "discover_tools", self.discover)
        settings = SimpleNamespace(notion_write_tool_names=(), notion_read_tool_names=(),
                                   notion_tool_policy="dynamic", notion_mcp_url="https://mcp.notion.com/mcp")
        oauth = SimpleNamespace(get_access_token=self.no_token, begin=self.begin,
                                store=SQLiteOAuthStore(str(tmp_path / "o.sqlite"), Fernet.generate_key().decode()))
        self.graph = notion_chat.build_direct_chat_graph(settings, lambda tools: self, MemorySaver(), oauth,
            identity_provider=lambda: "owner", guardrail=simulated_guardrail(), load_toolbox=self.load_toolbox)

    async def no_token(self, owner):
        return None

    async def begin(self, owner):
        return "https://mcp.notion.com/authorize?x"

    async def discover(self, settings, token):
        return []

    async def load_toolbox(self):
        async def web_search(search_query: str) -> str:
            self.calls += 1
            return await self.behaviour(self.calls)
        return [StructuredTool.from_function(coroutine=web_search, name="web_search", description="Search")], ()

    async def ainvoke(self, messages):
        return self.outputs.pop(0) if self.outputs else AIMessage(content="Done")

    def search(self, id="s1"):
        self.outputs.append(AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"search_query": "x"}, "id": id}]))

    async def turn(self, text):
        self.counter += 1
        return await self.graph.ainvoke({"messages": [HumanMessage(content=text, id=str(self.counter))]},
                                        {"configurable": {"thread_id": "t"}})


def tool_results(state):
    return [m for m in state["messages"] if m.type == "tool"]


def test_a_transient_read_failure_is_retried_once_then_succeeds(tmp_path, monkeypatch):
    async def flaky(n):
        if n == 1:
            raise httpx.ConnectError("down")
        return "results"
    async def scenario():
        h = Harness(tmp_path, monkeypatch, flaky)
        h.search()
        state = await h.turn("news?")
        assert h.calls == 2 and "results" in tool_results(state)[-1].content
    asyncio.run(scenario())


def test_a_read_that_times_out_is_retried_once_then_reported_without_hanging(tmp_path, monkeypatch):
    async def slow(n):
        await asyncio.sleep(5)
        return "late"
    async def scenario():
        h = Harness(tmp_path, monkeypatch, slow)
        h.search()
        state = await asyncio.wait_for(h.turn("news?"), 5)
        last = tool_results(state)[-1]
        assert h.calls == 2 and last.status == "error"
        assert json.loads(last.content)["code"] == "tool_timeout"
    asyncio.run(scenario())


def test_a_permanent_failure_is_not_retried_and_reads_cleanly(tmp_path, monkeypatch):
    async def broken(n):
        raise ValueError("bad input")
    async def scenario():
        h = Harness(tmp_path, monkeypatch, broken)
        h.search()
        state = await h.turn("news?")
        body = json.loads(tool_results(state)[-1].content)
        assert h.calls == 1 and body["retryable"] is False and "bad input" not in tool_results(state)[-1].content
    asyncio.run(scenario())


def test_the_tool_loop_stops_after_the_limit(tmp_path, monkeypatch):
    async def ok(n):
        return "more"
    async def scenario():
        h = Harness(tmp_path, monkeypatch, ok)
        for i in range(reliability.MAX_TOOL_ROUNDS + 3):
            h.search(id=f"s{i}")
        state = await h.turn("research everything")
        assert h.calls == reliability.MAX_TOOL_ROUNDS
        assert "I stopped after" in state["messages"][-1].content
    asyncio.run(scenario())


@pytest.mark.parametrize("error,transient", [
    (httpx.ConnectError("x"), True), (asyncio.TimeoutError(), True), (ConnectionError(), True),
    (httpx.HTTPStatusError("x", request=httpx.Request("GET", "https://a"), response=httpx.Response(503)), True),
    (httpx.HTTPStatusError("x", request=httpx.Request("GET", "https://a"), response=httpx.Response(429)), True),
    (httpx.HTTPStatusError("x", request=httpx.Request("GET", "https://a"), response=httpx.Response(403)), False),
    (ValueError("x"), False),
])
def test_transient_classification(error, transient):
    assert reliability.is_transient(error) is transient


def test_model_bounds_are_read_and_validated(monkeypatch):
    monkeypatch.setattr("savant.config.load_dotenv", lambda **_: None)
    monkeypatch.setenv("AZURE_OPENAI_BASE_URL", "https://m/")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "m")
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("MODEL_MAX_RETRIES", "1")
    settings = Settings.from_env()
    assert settings.model_timeout == 45 and settings.model_max_retries == 1
    monkeypatch.setenv("MODEL_MAX_RETRIES", "9")
    with pytest.raises(RuntimeError):
        Settings.from_env()
