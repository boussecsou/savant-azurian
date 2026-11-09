"""Correlated, secret-free logs for one call across the BFF and the agent (task 30)."""
import asyncio
import logging
from types import SimpleNamespace

from cryptography.fernet import Fernet
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver

from savant.bff_logging import SafeFormatter
from savant.correlation import correlation_id, is_correlation_id
from savant.notion_oauth import SQLiteOAuthStore
from savant.tools import notion_chat
from semantic_fakes import simulated_guardrail


def test_correlation_id_is_a_short_stable_hash():
    first = correlation_id("caresp_123")
    assert first == correlation_id("caresp_123") and is_correlation_id(first) and "123" not in first
    assert correlation_id("") == "-" and correlation_id(None) == "-"


def graph(tmp_path, monkeypatch, outputs):
    async def discover(settings, token):
        return []
    monkeypatch.setattr(notion_chat, "discover_tools", discover)

    async def no_token(owner):
        return None

    async def load_toolbox():
        async def web_search(search_query: str) -> str:
            return "results"
        return [StructuredTool.from_function(coroutine=web_search, name="web_search", description="Search")], ()

    class Model:
        async def ainvoke(self, messages):
            return outputs.pop(0)

    oauth = SimpleNamespace(get_access_token=no_token, begin=no_token,
                            store=SQLiteOAuthStore(str(tmp_path / "o.sqlite"), Fernet.generate_key().decode()))
    settings = SimpleNamespace(notion_write_tool_names=(), notion_read_tool_names=(),
                               notion_tool_policy="dynamic", notion_mcp_url="https://mcp.notion.com/mcp")
    return notion_chat.build_direct_chat_graph(settings, lambda tools: Model(), MemorySaver(), oauth,
        identity_provider=lambda: "owner", guardrail=simulated_guardrail(), load_toolbox=load_toolbox)


def run(g, text, turn_id):
    return asyncio.run(g.ainvoke({"messages": [HumanMessage(content=text, id=turn_id)]},
                                 {"configurable": {"thread_id": "t"}}))


def test_a_direct_answer_and_a_tool_call_share_one_correlation_per_turn(tmp_path, monkeypatch, caplog):
    outputs = [AIMessage(content="Hi."),
               AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"search_query": "secret plans"}, "id": "c1"}]),
               AIMessage(content="Here are the news.")]
    g = graph(tmp_path, monkeypatch, outputs)
    with caplog.at_level(logging.INFO, logger="savant.tools.notion_chat"):
        run(g, "hello there", "caresp_direct")
        run(g, "search my secret plans", "caresp_tool")
    direct, tool = correlation_id("caresp_direct"), correlation_id("caresp_tool")
    text = caplog.text
    assert f"turn_start correlation={direct}" in text and f"turn_end correlation={direct} path=direct outcome=answered" in text
    assert f"turn_step correlation={tool} path=tool round=1 tools=web_search" in text
    assert f"turn_end correlation={tool} path=tool outcome=answered" in text
    for private in ("hello there", "secret plans", "caresp_direct", "caresp_tool", "owner"):
        assert private not in text


def test_bff_completion_line_carries_only_a_valid_correlation():
    formatter = SafeFormatter()
    record = logging.LogRecord("savant.bff", logging.INFO, __file__, 1, "chat_relay_completed", None, None)
    record.correlation = correlation_id("caresp_123")
    assert formatter.format(record) == f"INFO chat_relay_completed correlation={record.correlation}"
    record.correlation = "caresp_123 token=abc"
    assert formatter.format(record) == "INFO chat_relay_completed"


def test_bff_logs_the_completed_relay_with_the_agent_side_correlation(tmp_path, caplog):
    from test_bff_api import OWNER_HEADERS, agent_stream, make_client
    from savant.notion_oauth import NotionOAuth
    store = SQLiteOAuthStore(str(tmp_path / "b.sqlite"), Fernet.generate_key().decode())
    service = NotionOAuth("http://localhost:8090/oauth/notion/callback", store)
    client, _ = make_client(service, lambda request: agent_stream(
        {"type": "response.output_text.delta", "delta": "Hi"},
        {"type": "response.completed", "response": {"id": "caresp_tool"}}))
    with caplog.at_level(logging.INFO, logger="savant.bff"):
        client.post("/api/chat/stream", headers=OWNER_HEADERS, json={"message": "Hi"})
    completed = [r for r in caplog.records if r.getMessage() == "chat_relay_completed"]
    assert completed and completed[0].correlation == correlation_id("caresp_tool")
