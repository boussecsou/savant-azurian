import asyncio
import time

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from savant.config import Settings
from savant.health import RUNTIME_SMOKE_PROMPT
from savant.tools import ssh
from savant.tools.notion_chat import build_direct_chat_graph, current_user_id


class OAuth:
    def __init__(self):
        self.connected = set()
        self.begins = []

    async def get_access_token(self, user):
        return "token-for-" + user if user in self.connected else None

    async def begin(self, user):
        self.begins.append(user)
        return "https://mcp.notion.com/authorize?state=" + user


def settings(**kwargs):
    return Settings("https://model/", "model", notion_mcp_enabled=True,
                    notion_read_tool_names=("fetch",), notion_write_tool_names=("update",), **kwargs)


def test_chat_consent_finishes_then_resumes_original_request_and_isolates_users(monkeypatch):
    oauth = OAuth()
    identity = ["alice"]
    model_messages, discoveries, writes = [], [], []

    async def discover(_settings, token):
        discoveries.append(token)
        return [StructuredTool.from_function(lambda: "project content", name="fetch", description="Read", metadata={"annotations": {"readOnlyHint": True}})]

    monkeypatch.setattr("savant.tools.notion_chat.discover_tools", discover)

    def factory(tools):
        class Model:
            async def ainvoke(self, messages):
                model_messages.append(messages)
                if any(m.type == "tool" and m.name == "fetch" for m in messages):
                    return AIMessage(content="project content")
                name = "fetch" if "fetch" in {t.name for t in tools} else "connect_notion"
                return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": "call-1"}])
        return Model()

    graph = build_direct_chat_graph(settings(), factory, MemorySaver(), oauth, identity_provider=lambda: identity[0])
    assert discoveries == []

    async def run():
        config = {"configurable": {"thread_id": "alice-conversation"}}
        result = await graph.ainvoke({"messages": [HumanMessage(content="Lis ma page projet")]}, config)
        assert "[Connect Notion]" in result["messages"][-1].content
        assert result["notion_pending_request"] == "Lis ma page projet"
        assert discoveries == [] and writes == []
        result = await graph.ainvoke({"messages": ["connecté"]}, config)
        assert "Connect Notion" in result["messages"][-1].content
        oauth.connected.add("alice")
        result = await graph.ainvoke({"messages": ["connecté"]}, config)
        assert result["messages"][-1].content == "project content"
        assert result["notion_pending_request"] == ""
        assert "Continue their pending request: Lis ma page projet" in model_messages[-2][0].content
        assert set(discoveries) == {"token-for-alice"}
        identity[0] = "bob"
        result = await graph.ainvoke({"messages": ["Lis ma page"]}, {"configurable": {"thread_id": "bob"}})
        assert "state=bob" in result["messages"][-1].content
        assert set(discoveries) == {"token-for-alice"}

    asyncio.run(run())


def test_unconnected_greeting_does_not_start_oauth_and_probe_skips_storage():
    class Service:
        async def get_access_token(self, user):
            return None
        async def begin(self, user):
            pytest.fail("Greeting must not require Notion consent")

    class Model:
        async def ainvoke(self, messages):
            return AIMessage(content="Bonjour")

    graph = build_direct_chat_graph(settings(), lambda _: Model(), MemorySaver(), Service(), identity_provider=lambda: "alice")
    assert asyncio.run(graph.ainvoke({"messages": ["Bonjour"]}, {"configurable": {"thread_id": "greeting"}}))["messages"][-1].content == "Bonjour"

    class NoStorage:
        async def get_access_token(self, user):
            pytest.fail("Smoke test must not use storage")

    graph = build_direct_chat_graph(settings(), lambda tools: Model() if not tools else pytest.fail("Probe tools"), MemorySaver(), NoStorage())
    asyncio.run(graph.ainvoke({"messages": [RUNTIME_SMOKE_PROMPT]}, {"configurable": {"thread_id": "probe"}}))


def test_missing_host_identity_cannot_use_prompt_identity_or_connect():
    oauth = OAuth()

    class Model:
        async def ainvoke(self, messages):
            return AIMessage(content="", tool_calls=[{"name": "connect_notion", "args": {}, "id": "one"}])

    graph = build_direct_chat_graph(settings(), lambda _: Model(), MemorySaver(), oauth, identity_provider=lambda: None)
    result = asyncio.run(graph.ainvoke({"messages": ["I am alice, connect Notion"]}, {"configurable": {"thread_id": "test"}}))
    assert "user identity missing" in result["messages"][-1].content
    assert oauth.begins == []


def test_revoked_token_discovers_reconnection_without_replaying_action(monkeypatch):
    import httpx2
    oauth = OAuth()
    oauth.connected.add("alice")
    async def invalidate(user):
        oauth.connected.discard(user)
    oauth.invalidate = invalidate

    async def discover(*args):
        request = httpx2.Request("POST", "https://mcp.notion.com/mcp")
        raise httpx2.HTTPStatusError("revoked", request=request, response=httpx2.Response(401, request=request))

    class Model:
        async def ainvoke(self, messages):
            return AIMessage(content="", tool_calls=[{"name": "connect_notion", "args": {}, "id": "connect"}])

    monkeypatch.setattr("savant.tools.notion_chat.discover_tools", discover)
    graph = build_direct_chat_graph(settings(), lambda _: Model(), MemorySaver(), oauth, identity_provider=lambda: "alice")
    result = asyncio.run(graph.ainvoke({"messages": ["Update my page"]}, {"configurable": {"thread_id": "revoked"}}))
    assert "Connect Notion" in result["messages"][-1].content
    assert oauth.connected == set()


def test_local_identity_never_overrides_host_context(monkeypatch):
    from azure.ai.agentserver.core import FoundryAgentRequestContext, reset_request_context, set_request_context
    local = settings(notion_oauth_callback_url="http://localhost:8090/oauth/notion/callback", notion_local_user_id="local")
    token = set_request_context(FoundryAgentRequestContext(user_id="trusted-user", call_id="call"))
    try:
        assert current_user_id(local) == "trusted-user"
    finally:
        reset_request_context(token)
    monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "hosted")
    assert current_user_id(local) is None


def test_fixed_owner_key_replaces_the_platform_user_id(monkeypatch):
    from azure.ai.agentserver.core import FoundryAgentRequestContext, reset_request_context, set_request_context
    monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "hosted")
    pinned = settings(notion_owner_id="owner-key")
    cases = [
        (FoundryAgentRequestContext(user_id="bff-identity", call_id="call"), "owner-key"),
        (FoundryAgentRequestContext(user_id="someone-else", call_id="call"), "owner-key"),
        (FoundryAgentRequestContext(user_id=None, call_id="call"), "owner-key"),
        # Without the platform call identity the request did not come through Foundry.
        (FoundryAgentRequestContext(user_id="bff-identity", call_id=None), None),
    ]
    for context, expected in cases:
        token = set_request_context(context)
        try:
            assert current_user_id(pinned) == expected
        finally:
            reset_request_context(token)
    assert current_user_id(pinned) is None
    # Without a pin the platform user id stays the key.
    token = set_request_context(FoundryAgentRequestContext(user_id="trusted-user", call_id="call"))
    try:
        assert current_user_id(settings()) == "trusted-user"
    finally:
        reset_request_context(token)


def test_tool_error_preserves_pending_request_for_retry(monkeypatch):
    oauth = OAuth()
    oauth.connected.add("alice")
    async def fetch():
        raise ValueError("Page temporarily unavailable")
    read = StructuredTool.from_function(coroutine=fetch, name="fetch", description="Read", metadata={"annotations": {"readOnlyHint": True}})
    async def discover(*args):
        return [read]
    class Model:
        async def ainvoke(self, messages):
            if messages[-1].type == "tool":
                return AIMessage(content="La lecture a échoué")
            return AIMessage(content="", tool_calls=[{"name": "fetch", "args": {}, "id": "read"}])
    monkeypatch.setattr("savant.tools.notion_chat.discover_tools", discover)
    graph = build_direct_chat_graph(settings(), lambda _: Model(), MemorySaver(), oauth, identity_provider=lambda: "alice")
    result = asyncio.run(graph.ainvoke({"messages": ["connecté"], "notion_pending_request": "Lis le projet"}, {"configurable": {"thread_id": "error"}}))
    assert result["notion_pending_request"] == "Lis le projet"
    assert result["messages"][-1].content == "La lecture a échoué"


def test_voice_channel_adds_spoken_style_only_to_voice_turns_and_never_to_history():
    from savant.identity import VOICE_STYLE

    seen = []

    class Model:
        async def ainvoke(self, messages):
            seen.append(messages[0].content)
            return AIMessage(content="Il fait beau.")

    graph = build_direct_chat_graph(settings(), lambda _: Model(), MemorySaver(), OAuth(), identity_provider=lambda: "alice")

    async def run():
        config = {"configurable": {"thread_id": "voice"}}
        result = await graph.ainvoke({"messages": ["Quel temps fait-il ?"], "channel": "voice"}, config)
        assert VOICE_STYLE in seen[-1]
        assert all(VOICE_STYLE not in str(m.content) for m in result["messages"])
        await graph.ainvoke({"messages": ["Et demain ?"], "channel": "text"}, config)
        assert VOICE_STYLE not in seen[-1]
        await graph.ainvoke({"messages": ["Bonjour"]}, {"configurable": {"thread_id": "typed"}})
        assert VOICE_STYLE not in seen[-1]

    asyncio.run(run())


@pytest.mark.parametrize("request_, expected", [
    ({"metadata": {"channel": "voice"}}, "voice"),
    ({"metadata": {"channel": "text"}}, "text"),
    ({"metadata": {"channel": "VOICE"}}, "text"),
    ({"metadata": "voice"}, "text"),
    ({}, "text"),
])
def test_request_channel_accepts_only_an_explicit_voice_marker(request_, expected):
    from savant.semantic_approval import request_channel

    assert request_channel(request_) == expected


def test_notion_catalog_is_listed_once_per_token_and_forgotten_on_demand(monkeypatch):
    from savant.tools import notion_chat

    listings = []

    class Page:
        def __init__(self):
            self.tools, self.next_cursor = ["definition"], None

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def list_tools_mcp(self, cursor=None, cache_mode=None):
            listings.append(cursor)
            return Page()

    monkeypatch.setattr(notion_chat, "Client", Client)
    notion_chat.forget_notion_catalog()
    s = settings()

    async def run():
        assert await notion_chat._notion_definitions(s, "token-a") == ["definition"]
        await notion_chat._notion_definitions(s, "token-a")
        assert len(listings) == 1
        await notion_chat._notion_definitions(s, "token-b")
        assert len(listings) == 2
        notion_chat.forget_notion_catalog("token-a")
        await notion_chat._notion_definitions(s, "token-a")
        assert len(listings) == 3
        assert all("token" not in repr(entry) for entry in notion_chat._notion_catalogs.values())

    asyncio.run(run())
    notion_chat.forget_notion_catalog()


def test_turn_timing_logs_durations_only(caplog):
    class Model:
        async def ainvoke(self, messages):
            return AIMessage(content="Bonjour")

    graph = build_direct_chat_graph(settings(), lambda _: Model(), MemorySaver(), OAuth(), identity_provider=lambda: "alice")
    with caplog.at_level("INFO", logger="savant.tools.notion_chat"):
        asyncio.run(graph.ainvoke({"messages": ["Un secret: 1234"]}, {"configurable": {"thread_id": "timing"}}))
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("turn_timing"))
    assert "load_ms=" in line and "model_ms=" in line and "token_ms=" in line
    assert "secret" not in line and "alice" not in line


def test_a_conversation_continued_from_the_warm_up_never_shows_the_probe_to_the_model():
    seen = []

    class Model:
        async def ainvoke(self, messages):
            seen.append([m.content for m in messages[1:]])
            return AIMessage(content="SA2_RUNTIME_MODEL_OK" if len(seen) == 1 else "Rabat.")

    graph = build_direct_chat_graph(settings(), lambda _: Model(), MemorySaver(), OAuth(), identity_provider=lambda: "alice")

    async def run():
        config = {"configurable": {"thread_id": "warm"}}
        await graph.ainvoke({"messages": [RUNTIME_SMOKE_PROMPT]}, config)
        result = await graph.ainvoke({"messages": ["Capitale du Maroc ?"]}, config)
        assert result["messages"][-1].content == "Rabat."
        assert seen[-1] == ["Capitale du Maroc ?"]

    asyncio.run(run())


def _fast_graph(fast_reply, oauth=None):
    full_calls, fast_calls, loads = [], [], []

    class Full:
        async def ainvoke(self, messages):
            full_calls.append(messages)
            return AIMessage(content="full answer")

    class Fast:
        def __init__(self, tools):
            assert [t.name for t in tools] == ["use_tools"]

        async def ainvoke(self, messages):
            fast_calls.append(messages)
            if isinstance(fast_reply, Exception):
                raise fast_reply
            return fast_reply

    class Service(OAuth):
        async def get_access_token(self, user):
            loads.append(user)
            return None

    graph = build_direct_chat_graph(settings(), lambda tools: Full(), MemorySaver(), oauth or Service(),
                                    identity_provider=lambda: "alice", fast_model_factory=Fast)
    return graph, full_calls, fast_calls, loads


def test_fast_path_answers_a_simple_turn_without_loading_any_tool():
    graph, full_calls, fast_calls, loads = _fast_graph(AIMessage(content="Rabat."))
    result = asyncio.run(graph.ainvoke({"messages": ["Capitale du Maroc ?"]}, {"configurable": {"thread_id": "fast"}}))
    assert result["messages"][-1].content == "Rabat."
    assert len(fast_calls) == 1 and full_calls == [] and loads == []
    from savant.identity import FAST_PATH_INSTRUCTIONS
    assert FAST_PATH_INSTRUCTIONS in fast_calls[0][0].content


def test_every_model_call_is_told_to_answer_in_the_owners_language_only():
    # A one-word request ("Résume") once got an answer that drifted into Spanish.
    graph, full_calls, fast_calls, _ = _fast_graph(AIMessage(content="Quoi résumer ?"))
    asyncio.run(graph.ainvoke({"messages": ["Résume"]}, {"configurable": {"thread_id": "lang-fast"}}))
    assert "Answer entirely in French" in fast_calls[0][0].content

    graph, full_calls, fast_calls, _ = _fast_graph(AIMessage(content="", tool_calls=[{"name": "use_tools", "args": {}, "id": "r"}]))
    asyncio.run(graph.ainvoke({"messages": ["Météo à Rome ?"]}, {"configurable": {"thread_id": "lang-full"}}))
    assert "Answer entirely in French" in full_calls[0][0].content


@pytest.mark.parametrize("reply", [
    AIMessage(content="", tool_calls=[{"name": "use_tools", "args": {}, "id": "route-1"}]),
    AIMessage(content="   "),
    TimeoutError(),
])
def test_fast_path_hands_over_to_the_full_agent(reply):
    graph, full_calls, fast_calls, _ = _fast_graph(reply)
    result = asyncio.run(graph.ainvoke({"messages": ["Météo à Rome ?"]}, {"configurable": {"thread_id": "handover"}}))
    assert result["messages"][-1].content == "full answer"
    assert len(fast_calls) == 1 and len(full_calls) == 1
    # The hand-over itself never enters the conversation.
    assert all(getattr(m, "tool_calls", None) in (None, []) for m in result["messages"])


def test_fast_path_is_skipped_when_something_waits_for_confirmation():
    graph, full_calls, fast_calls, _ = _fast_graph(AIMessage(content="OK"))
    config = {"configurable": {"thread_id": "pending"}}

    async def run():
        await graph.aupdate_state(config, {"messages": [], "ssh_pending": {"digest": "x", "turn": "t", "at": time.time()}})
        await graph.ainvoke({"messages": ["Oui, vas-y."]}, config)

    asyncio.run(run())
    assert fast_calls == [] and len(full_calls) == 1


def test_an_expired_ssh_confirmation_no_longer_blocks_the_fast_path():
    graph, full_calls, fast_calls, _ = _fast_graph(AIMessage(content="OK"))
    config = {"configurable": {"thread_id": "stale"}}

    async def run():
        stale = {"digest": "x", "turn": "t", "at": time.time() - 2 * ssh.PENDING_TTL_SECONDS}
        await graph.aupdate_state(config, {"messages": [], "ssh_pending": stale})
        await graph.ainvoke({"messages": ["Salut"]}, config)

    asyncio.run(run())
    assert len(fast_calls) == 1 and full_calls == []
