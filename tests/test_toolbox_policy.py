"""Toolbox calls (Outlook, web search) through the chat graph; tools, model and Azure are simulated."""

import asyncio
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver
from semantic_fakes import simulated_guardrail

from savant.notion_oauth import SQLiteOAuthStore
from savant.tools import notion_chat
from savant.tools import toolbox_policy as policy

P = "outlook-sa2___outlook_"
SEND = {"emailMessage": {"To": "me@gmail.com", "Subject": "Hello", "Body": "Line one\nLine two"}}


# -- policy ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        P + "GetEmails",
        P + "GetEmailsV2",
        P + "GetEmail",
        P + "GetAttachment",
        P + "CalendarGetTable",
        P + "ContactGetTable",
        P + "MarkAsRead",
        P + "Flag",
        P + "Move",
        "tool_search",
        "web_search_m9bcyr",
        "oauth_consent_required",
    ],
)
def test_known_reads_and_reversible_bookkeeping_run_freely(name):
    assert not policy.requires_approval(name, {})
    assert not policy.requires_approval("call_tool", {"name": name, "arguments": {}})


@pytest.mark.parametrize(
    "name",
    [
        P + "SendEmail",
        P + "SendEmailV2",
        P + "ReplyToV3",
        P + "DeleteEmail",
        P + "BrandNewOperation",
        "code_interpreter_spmx9p",
        "FoundryMCPServerpreview",
        "notion-create-pages",
        "something_else",
    ],
)
def test_sends_deletes_and_anything_unknown_are_protected(name):
    assert policy.requires_approval(name, {})
    assert policy.requires_approval("call_tool", {"name": name, "arguments": {}})


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"name": 3},
        {"name": "call_tool", "arguments": {}},
        {"name": P + "GetEmails", "arguments": "x"},
        {"arguments": {}},
        None,
        "x",
    ],
)
def test_malformed_dispatch_is_protected(args):
    assert policy.requires_approval("call_tool", args)


def test_the_wrapper_cannot_launder_a_send_as_a_read():
    wrapped = {"name": P + "SendEmailV2", "arguments": SEND}
    assert policy.requires_approval("call_tool", wrapped)
    assert policy.effective_call("call_tool", wrapped) == (P + "SendEmailV2", SEND, True)


def test_confirmation_text_is_built_from_the_exact_arguments():
    kind, text = policy.describe("call_tool", {"name": P + "SendEmailV2", "arguments": SEND})
    assert kind == "send" and "me@gmail.com" in text and "Hello" in text
    assert "> Line one\n> Line two" in text
    kind, text = policy.describe(P + "DeleteEmail", {"messageId": "AAMkAG" + "x" * 40})
    assert kind == "delete" and "`" + "x" * 12 + "`" in text
    reply = {"messageId": "id", "replyParameters": {"Body": "Thanks", "ReplyAll": True}}
    assert (
        "reply" in policy.describe(P + "ReplyToV3", reply)[1]
        and "Reply to all:** yes" in policy.describe(P + "ReplyToV3", reply)[1]
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"emailMessage": {"To": "a@b.c", "Subject": "s", "Body": "b", "Attachments": [{"Name": "x"}]}},
        {"emailMessage": {"To": "a@b.c", "From": "boss@corp.com", "Body": "b"}},
        {"emailMessage": {"To": "a@b.c", "ReplyTo": "x@y.z", "Body": "b"}},
        {"emailMessage": {"To": "a@b.c", "Body": "x" * (policy.MAX_BODY_CHARS + 1)}},
        {"emailMessage": {"Subject": "no recipient", "Body": "b"}},
        {"emailMessage": {"To": "a@b.c", "Body": "b"}, "extra": 1},
        {"emailMessage": "text"},
    ],
)
def test_sends_that_cannot_be_shown_in_full_are_not_presentable(arguments):
    assert policy.describe(P + "SendEmailV2", arguments) is None
    assert (
        notion_chat._presentable({"name": "call_tool", "args": {"name": P + "SendEmailV2", "arguments": arguments}})
        is False
    )


# -- through the graph -----------------------------------------------------------


class Harness:
    def __init__(self, tmp_path, monkeypatch, *, tool_search=True, toolbox_error=None):
        self.calls, self.outputs, self.counter, self.model_calls = [], [], 0, 0
        self.toolbox_error, self.system_prompts = toolbox_error, []
        self.settings = SimpleNamespace(
            notion_write_tool_names=(),
            notion_read_tool_names=(),
            notion_tool_policy="dynamic",
            notion_mcp_url="https://mcp.notion.com/mcp",
        )
        self.oauth = SimpleNamespace(
            get_access_token=self.access,
            begin=self.begin,
            store=SQLiteOAuthStore(str(tmp_path / "oauth.sqlite"), Fernet.generate_key().decode()),
        )
        monkeypatch.setattr(notion_chat, "discover_tools", self.discover)
        self.tool_search = tool_search
        self.graph = notion_chat.build_direct_chat_graph(
            self.settings,
            lambda tools: self,
            MemorySaver(),
            self.oauth,
            identity_provider=lambda: "owner",
            guardrail=simulated_guardrail(),
            load_toolbox=self.load_toolbox,
        )

    async def access(self, owner):
        return None

    async def begin(self, owner):
        return "https://mcp.notion.com/authorize?fake"

    async def discover(self, settings, token):
        return []

    async def load_toolbox(self):
        if self.toolbox_error:
            raise self.toolbox_error

        async def call_tool(name: str, arguments: dict | None = None) -> str:
            self.calls.append((name, arguments))
            return "ok"

        async def tool_search(query: str) -> str:
            return "[]"

        async def direct(**kwargs) -> str:
            self.calls.append(("direct", kwargs))
            return "ok"

        tools = [
            StructuredTool.from_function(coroutine=call_tool, name="call_tool", description="Dispatch"),
            StructuredTool.from_function(coroutine=tool_search, name="tool_search", description="Search"),
        ]
        if not self.tool_search:
            tools.append(
                StructuredTool.from_function(
                    coroutine=direct,
                    name=P + "SendEmailV2",
                    description="Send",
                    args_schema={"type": "object", "properties": {"emailMessage": {"type": "object"}}},
                )
            )
        return tools, ()

    async def ainvoke(self, messages):
        self.system_prompts.append(messages[0].content)
        self.model_calls += 1
        return self.outputs.pop(0) if self.outputs else AIMessage(content="Done")

    async def turn(self, text, *, thread="thread"):
        self.counter += 1
        return await self.graph.ainvoke(
            {"messages": [HumanMessage(content=text, id=str(self.counter))]}, {"configurable": {"thread_id": thread}}
        )

    def dispatch(self, name, arguments=None, id="c1"):
        self.outputs.append(
            AIMessage(
                content="",
                tool_calls=[{"name": "call_tool", "args": {"name": name, "arguments": arguments or {}}, "id": id}],
            )
        )


def test_reads_and_bookkeeping_run_without_confirmation(tmp_path, monkeypatch):
    async def scenario():
        h = Harness(tmp_path, monkeypatch)
        h.dispatch(P + "GetEmails", {"folderPath": "Inbox", "top": 5})
        state = await h.turn("Any new mail?")
        assert h.calls == [(P + "GetEmails", {"folderPath": "Inbox", "top": 5})]
        assert not state.get("notion_pending_actions")
        h.dispatch(P + "MarkAsRead", {"messageId": "m1"}, id="c2")
        await h.turn("Mark it read")
        assert h.calls[-1] == (P + "MarkAsRead", {"messageId": "m1"})

    asyncio.run(scenario())


def test_send_shows_the_exact_message_runs_only_after_approval_and_only_once(tmp_path, monkeypatch):
    async def scenario():
        h = Harness(tmp_path, monkeypatch)
        h.dispatch(P + "SendEmailV2", SEND)
        state = await h.turn("Email me the notes")
        assert h.calls == [] and len(state["notion_pending_actions"]) == 1
        question = state["messages"][-1].content
        assert "send this email" in question and "me@gmail.com" in question and "> Line one" in question
        state = await h.turn("Yes, do it")
        assert h.calls == [(P + "SendEmailV2", SEND)]
        assert not state["notion_pending_actions"]
        state = await h.turn("Yes, do it")  # replay of the consent
        assert h.calls == [(P + "SendEmailV2", SEND)]

    asyncio.run(scenario())


def test_refusing_a_send_runs_nothing(tmp_path, monkeypatch):
    async def scenario():
        h = Harness(tmp_path, monkeypatch)
        h.dispatch(P + "SendEmailV2", SEND)
        await h.turn("Email me the notes")
        state = await h.turn("No")
        assert h.calls == [] and not state["notion_pending_actions"]

    asyncio.run(scenario())


def test_delete_and_unknown_tools_ask_first(tmp_path, monkeypatch):
    async def scenario():
        h = Harness(tmp_path, monkeypatch)
        h.dispatch(P + "DeleteEmail", {"messageId": "AAMkAGabc123"})
        state = await h.turn("Delete that mail")
        assert h.calls == [] and "delete the email" in state["messages"][-1].content
        (tmp_path / "b").mkdir()
        h = Harness(tmp_path / "b", monkeypatch)
        h.dispatch("code_interpreter_spmx9p", {"code": "print(1)"})
        state = await h.turn("Run it")
        assert h.calls == [] and len(state["notion_pending_actions"]) == 1

    asyncio.run(scenario())


def test_a_send_that_cannot_be_shown_in_full_is_refused_not_approved_blind(tmp_path, monkeypatch):
    async def scenario():
        h = Harness(tmp_path, monkeypatch)
        h.dispatch(P + "SendEmailV2", {"emailMessage": {"To": "a@b.c", "Body": "x", "Attachments": [{"Name": "f"}]}})
        state = await h.turn("Send it with the file")
        assert h.calls == [] and not state.get("notion_pending_actions")
        assert "can't present" in state["messages"][-1].content

    asyncio.run(scenario())


def test_a_directly_listed_send_tool_is_gated_too(tmp_path, monkeypatch):
    async def scenario():
        h = Harness(tmp_path, monkeypatch, tool_search=False)
        h.outputs.append(AIMessage(content="", tool_calls=[{"name": P + "SendEmailV2", "args": SEND, "id": "d1"}]))
        state = await h.turn("Email me the notes")
        assert h.calls == [] and "send this email" in state["messages"][-1].content
        await h.turn("Yes")
        assert h.calls == [("direct", SEND)]

    asyncio.run(scenario())


def test_a_failing_toolbox_does_not_take_the_chat_down(tmp_path, monkeypatch, caplog):
    import logging

    class Denied(Exception):
        response = SimpleNamespace(status_code=403)

    async def scenario():
        h = Harness(
            tmp_path,
            monkeypatch,
            toolbox_error=Denied("sign in at https://x.consent.azure-apihub.net/login?data=SECRETDATA " + "k" * 50),
        )
        h.outputs.append(AIMessage(content="Hello."))
        with caplog.at_level(logging.WARNING):
            state = await h.turn("Hi")
        assert state["messages"][-1].content == "Hello."
        assert "toolbox (Outlook" in h.system_prompts[-1] and "unavailable" in h.system_prompts[-1]
        assert "Use only tools that were actually returned" not in h.system_prompts[-1]
        assert "toolbox_unavailable error_type=Denied status=403" in caplog.text
        assert "SECRETDATA" not in caplog.text and "azure-apihub" not in caplog.text and "k" * 50 not in caplog.text
        assert "detail=sign in at <url>" in caplog.text

    asyncio.run(scenario())


def test_the_model_is_told_the_current_date(tmp_path, monkeypatch):
    async def scenario():
        h = Harness(tmp_path, monkeypatch)
        h.outputs.append(AIMessage(content="Hi."))
        await h.turn("What day is it?")
        assert "Current date and time (Africa/Casablanca):" in h.system_prompts[-1]
        # The changing clock goes last so the long instructions stay a cacheable prefix.
        assert h.system_prompts[-1].rstrip().splitlines()[-1].startswith("Current date and time")

    asyncio.run(scenario())
