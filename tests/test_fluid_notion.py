"""Exercise the automatic edit and deletion gate with simulated MCP tools."""

import asyncio
import json

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from semantic_fakes import asks_confirmation
from test_semantic_chat import Harness

from savant.tools.notion_policy import may_execute_without_approval, requires_approval

PAGE = "3eceba09-0000-4000-8000-000000000001"


def candidate(name):
    async def execute(**kwargs):
        return "ok"

    return StructuredTool.from_function(coroutine=execute, name=name, description="Notion operation")


@pytest.mark.parametrize(
    "name", ["notion-create-pages", "notion-create-folder", "notion-duplicate-page", "notion-restore-pages"]
)
def test_known_additive_notion_tools_are_automatic(name):
    assert may_execute_without_approval(candidate(name), {})


def test_folder_additions_are_automatic_but_file_removal_is_protected():
    tool = candidate("notion-update-folder")
    assert may_execute_without_approval(tool, {"folder_id": PAGE, "command": "add_subfolder", "title": "Notes"})
    assert may_execute_without_approval(tool, {"folder_id": PAGE, "command": "add_files", "file_upload_ids": ["file"]})
    assert not may_execute_without_approval(tool, {"folder_id": PAGE, "command": "remove_files", "file_urls": ["file"]})


@pytest.mark.parametrize(
    "arguments",
    [
        {"command": "insert_content", "page_id": PAGE, "content": "New paragraph"},
        {"command": "update_properties", "page_id": PAGE, "properties": {"title": "New title"}},
        {
            "command": "update_content",
            "page_id": PAGE,
            "content_updates": [
                {"old_str": "<table><tr><td><b>Monday</b></td><td>C++</td></tr></table>", "new_str": "| Monday | C++ |"}
            ],
        },
    ],
)
def test_ordinary_additions_and_content_preserving_formatting_are_automatic(arguments):
    assert may_execute_without_approval(candidate("notion-update-page"), arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        {"command": "update_content", "content_updates": [{"old_str": "Keep and remove", "new_str": "Keep"}]},
        {"command": "update_content", "content_updates": [{"old_str": "C++", "new_str": "C"}]},
        {"command": "update_content", "content_updates": [{"old_str": "Important", "new_str": ""}]},
        {
            "command": "update_content",
            "content_updates": [{"old_str": '<mention url="https://notion.so/a" />', "new_str": ""}],
        },
        {"command": "replace_content", "new_str": "Replacement"},
        {"command": "update_properties", "properties": {"title": ""}},
        {"command": "update_properties", "properties": {"relations": ["one retained relation"]}},
        {"command": "insert_content", "content": "x", "allow_deleting_content": True},
        {"command": "insert_content", "content": "x", "template_id": "unknown-effect"},
        {
            "command": "update_content",
            "content_updates": [{"old_str": "Keep", "new_str": "Keep", "future_option": True}],
        },
        {"command": "new_unknown_command", "content": "x"},
    ],
)
def test_removal_or_unverifiable_effect_requires_approval(arguments):
    assert not may_execute_without_approval(candidate("notion-update-page"), arguments)


def test_new_delete_tool_cannot_bypass_gate_with_a_wrong_read_hint():
    tool = candidate("notion-delete-something").model_copy(update={"metadata": {"readOnlyHint": True}})
    assert requires_approval(tool)
    assert not may_execute_without_approval(tool, {})


def test_approval_never_hides_additional_effects_or_a_large_scope():
    from savant.tools.notion_chat import _presentable

    base = {
        "name": "notion-update-page",
        "args": {
            "page_id": PAGE,
            "command": "update_content",
            "content_updates": [{"old_str": "Keep and remove", "new_str": "Keep"}],
        },
    }
    assert _presentable(base)
    hidden = {"name": base["name"], "args": {**base["args"], "properties": {"status": "changed"}}}
    assert not _presentable(hidden)
    large = {"name": base["name"], "args": {**base["args"], "content_updates": [{"old_str": "x" * 301, "new_str": ""}]}}
    assert not _presentable(large)


def test_formatting_request_updates_page_in_one_turn_without_confirmation(tmp_path, monkeypatch):
    async def scenario():
        h = Harness(tmp_path, monkeypatch)
        writes = []

        async def update(page_id: str, command: str, content_updates: list[dict]):
            writes.append((page_id, content_updates))
            return "updated"

        h.catalog = [
            StructuredTool.from_function(coroutine=update, name="notion-update-page", description="Update page")
        ]
        changes = [{"old_str": "<table><tr><td>Monday</td><td>C++</td></tr></table>", "new_str": "| Monday | C++ |"}]
        h.outputs.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "notion-update-page",
                        "args": {"page_id": PAGE, "command": "update_content", "content_updates": changes},
                        "id": "format",
                    }
                ],
            )
        )
        state = await h.turn("Improve the presentation without removing content")
        assert writes == [(PAGE, changes)]
        assert not state.get("notion_pending_actions")
        assert not asks_confirmation(state["messages"][-1].content)

    asyncio.run(scenario())


def test_automatic_addition_requires_the_durable_ledger(tmp_path, monkeypatch):
    async def scenario():
        h = Harness(tmp_path, monkeypatch, durable=False)
        effects = []

        async def update(page_id: str, command: str, content: str):
            effects.append(content)
            return "added"

        h.catalog = [StructuredTool.from_function(coroutine=update, name="notion-update-page", description="Update")]
        h.outputs.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "notion-update-page",
                        "args": {"page_id": PAGE, "command": "insert_content", "content": "Note"},
                        "id": "add",
                    }
                ],
            )
        )
        state = await h.turn("Add a note")
        assert effects == []
        assert "tool_execution_failed" in state["messages"][-1].content

    asyncio.run(scenario())


def test_automatic_write_failure_does_not_retry_or_run_later_batch_actions(tmp_path, monkeypatch):
    async def scenario():
        h = Harness(tmp_path, monkeypatch)
        effects = []

        async def update(page_id: str, command: str, content: str):
            effects.append(content)
            raise TimeoutError("uncertain result")

        h.catalog = [StructuredTool.from_function(coroutine=update, name="notion-update-page", description="Update")]
        h.outputs.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "notion-update-page",
                        "args": {"page_id": PAGE, "command": "insert_content", "content": "first"},
                        "id": "first",
                    },
                    {
                        "name": "notion-update-page",
                        "args": {"page_id": PAGE, "command": "insert_content", "content": "second"},
                        "id": "second",
                    },
                ],
            )
        )
        state = await h.turn("Add both notes")
        assert effects == ["first"]
        assert "tool_execution_failed" in state["messages"][-1].content
        assert h.model_calls == 1

    asyncio.run(scenario())


def test_add_and_delete_batch_executes_addition_then_requests_one_short_confirmation(tmp_path, monkeypatch):
    async def scenario():
        h = Harness(tmp_path, monkeypatch)
        effects = []

        async def update(page_id: str, command: str, content: str):
            effects.append(("add", page_id, content))
            return "added"

        async def delete(page_ids: list[str], user_confirmed: bool = False):
            effects.append(("delete", page_ids, user_confirmed))
            return "deleted"

        h.catalog = [
            StructuredTool.from_function(coroutine=update, name="notion-update-page", description="Update page"),
            StructuredTool.from_function(coroutine=delete, name="notion-delete-pages", description="Delete pages"),
        ]
        h.outputs.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "notion-update-page",
                        "args": {"page_id": PAGE, "command": "insert_content", "content": "Note"},
                        "id": "add",
                    },
                    {
                        "name": "notion-delete-pages",
                        "args": {"page_ids": [PAGE], "user_confirmed": False},
                        "id": "delete",
                    },
                ],
            )
        )
        state = await h.turn("Add the note and delete the page")
        assert effects == [("add", PAGE, "Note")]
        question = state["messages"][-1].content
        assert asks_confirmation(question) and "trash" in question
        assert "https://www.notion.so/" in question and "user_confirmed" not in question
        assert len(question) < 200
        await h.turn("Non, annule")
        assert effects == [("add", PAGE, "Note")]

    asyncio.run(scenario())


def test_confirmed_deletion_sets_provider_flag_only_after_owner_approval(tmp_path, monkeypatch):
    async def scenario():
        h = Harness(tmp_path, monkeypatch)
        effects = []

        async def delete(page_ids: list[str], user_confirmed: bool = False):
            effects.append((page_ids, user_confirmed))
            return "deleted"

        h.catalog = [
            StructuredTool.from_function(coroutine=delete, name="notion-delete-pages", description="Delete pages")
        ]
        h.outputs.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "notion-delete-pages",
                        "args": {"page_ids": [PAGE], "user_confirmed": False},
                        "id": "delete",
                    }
                ],
            )
        )
        state = await h.turn("Delete the page")
        assert effects == [] and len(state["notion_pending_actions"]) == 1
        state = await h.turn("Oui, je confirme")
        assert effects == [([PAGE], True)]
        assert state["messages"][-1].content == "Done: I moved the page to the trash."
        assert "tool_returned" not in state["messages"][-1].content
        await h.turn("Oui, je confirme")
        assert len(effects) == 1

    asyncio.run(scenario())


def test_a_french_request_gets_a_french_question_with_the_page_title_and_a_french_outcome(tmp_path, monkeypatch):
    async def scenario():
        h = Harness(tmp_path, monkeypatch)
        effects = []
        fetched = []

        async def delete(page_ids: list[str], user_confirmed: bool = False):
            effects.append((page_ids, user_confirmed))
            return "deleted"

        async def fetch(id: str):
            fetched.append(id)
            return '{"title": "Rapport technique — état du VPS", "url": "https://www.notion.so/x", "text": "..."}'

        h.catalog = [
            StructuredTool.from_function(coroutine=delete, name="notion-delete-pages", description="Delete pages"),
            StructuredTool.from_function(coroutine=fetch, name="notion-fetch", description="Fetch a page"),
        ]
        h.outputs.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "notion-delete-pages",
                        "args": {"page_ids": [PAGE], "user_confirmed": False},
                        "id": "delete",
                    }
                ],
            )
        )
        state = await h.turn("Je veux que tu supprimes le rapport technique de mon VPS")
        question = state["messages"][-1].content
        assert fetched == [PAGE] and effects == []
        assert question.startswith("Tu veux que je mette la page [Rapport technique — état du VPS](")
        assert question.endswith("à la corbeille ?") and "Confirmation required" not in question
        state = await h.turn("Je confirme")
        assert effects == [([PAGE], True)]
        assert (
            state["messages"][-1].content
            == "C'est fait, j'ai mis la page « Rapport technique — état du VPS » à la corbeille."
        )

    asyncio.run(scenario())


def test_the_question_survives_a_missing_title_and_a_cancel_runs_nothing(tmp_path, monkeypatch):
    async def scenario():
        h = Harness(tmp_path, monkeypatch)
        effects = []

        async def delete(page_ids: list[str], user_confirmed: bool = False):
            effects.append(page_ids)
            return "deleted"

        async def fetch(id: str):
            raise RuntimeError("down")

        h.catalog = [
            StructuredTool.from_function(coroutine=delete, name="notion-delete-pages", description="Delete pages"),
            StructuredTool.from_function(coroutine=fetch, name="notion-fetch", description="Fetch a page"),
        ]
        h.outputs.append(
            AIMessage(
                content="", tool_calls=[{"name": "notion-delete-pages", "args": {"page_ids": [PAGE]}, "id": "delete"}]
            )
        )
        state = await h.turn("Supprime cette page s'il te plaît")
        assert state["messages"][-1].content.startswith("Tu veux que je mette [cette page](")
        state = await h.turn("Non, annule")
        assert effects == [] and state["notion_pending_actions"] == []

    asyncio.run(scenario())


def test_tracking_only_arguments_do_not_make_a_deletion_unpresentable(tmp_path, monkeypatch):
    """The Notion MCP schema declares optional `skill` and `telemetry` fields; models often fill them.
    They only describe the caller, so they must neither block the confirmation nor be sent."""

    async def scenario():
        h = Harness(tmp_path, monkeypatch)
        effects = []

        async def delete(**arguments):
            effects.append(arguments)
            return "deleted"

        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["page_ids"],
            "properties": {
                "page_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20},
                "user_confirmed": {"type": "boolean"},
                "instructions_version": {"type": "string"},
                "skill": {"type": "string"},
                "telemetry": {"type": "object", "properties": {"intent": {"type": "string"}}},
            },
        }
        h.catalog = [
            StructuredTool(name="notion-delete-pages", description="Delete pages", args_schema=schema, coroutine=delete)
        ]
        h.outputs.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "notion-delete-pages",
                        "id": "delete",
                        "args": {
                            "page_ids": [PAGE],
                            "skill": "notion-cleanup",
                            "telemetry": {"intent": "Delete an empty past meeting task."},
                        },
                    }
                ],
            )
        )
        state = await h.turn("Delete the page")
        assert "can't present" not in state["messages"][-1].content
        assert asks_confirmation(state["messages"][-1].content)
        assert effects == [] and len(state["notion_pending_actions"]) == 1
        await h.turn("Oui, je confirme")
        assert effects == [{"page_ids": [PAGE], "user_confirmed": True}]

    asyncio.run(scenario())


@pytest.mark.parametrize("cursor", ["", "null", " None ", None])
def test_a_placeholder_cursor_is_not_sent_but_a_real_one_is(tmp_path, monkeypatch, cursor):
    """Notion refuses a first page asked with a made-up cursor; the next page needs the real one."""

    async def scenario():
        h = Harness(tmp_path, monkeypatch)
        received = []

        async def listing(cursor: str | None = None, limit: int | None = None):
            received.append({"cursor": cursor, "limit": limit})
            return "pages"

        h.catalog = [
            StructuredTool.from_function(
                coroutine=listing,
                name="notion-list-private-pages",
                description="List pages",
                metadata={"mcp": {"tool": {"annotations": {"readOnlyHint": True}}}},
            )
        ]
        h.outputs.append(
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "notion-list-private-pages", "id": "first", "args": {"cursor": cursor, "limit": 50}}
                ],
            )
        )
        await h.turn("List my root pages")
        assert received == [{"cursor": None, "limit": 50}]
        h.outputs.append(
            AIMessage(
                content="",
                tool_calls=[{"name": "notion-list-private-pages", "id": "next", "args": {"cursor": "opaque-123"}}],
            )
        )
        await h.turn("And the next ones")
        assert received[-1]["cursor"] == "opaque-123"

    asyncio.run(scenario())


def test_toolbox_names_are_not_treated_as_official_notion_tools(tmp_path, monkeypatch):
    async def scenario():
        h = Harness(tmp_path, monkeypatch)
        effects = []

        async def create(pages: list[str]):
            effects.append(pages)
            return "created"

        toolbox = StructuredTool.from_function(coroutine=create, name="notion-create-pages", description="Dispatch")
        h.catalog = []

        async def load_toolbox():
            return [toolbox], None

        from savant.tools.notion_chat import build_direct_chat_graph

        h.graph = build_direct_chat_graph(
            h.settings,
            lambda _: h,
            h.saver,
            h.oauth,
            identity_provider=lambda: h.owner,
            guardrail=h.guardrail,
            load_toolbox=load_toolbox,
        )
        h.outputs.append(
            AIMessage(content="", tool_calls=[{"name": toolbox.name, "args": {"pages": ["x"]}, "id": "toolbox"}])
        )
        state = await h.turn("Create a page")
        assert effects == [] and state["notion_pending_actions"]

    asyncio.run(scenario())


def test_automatic_addition_replayed_from_checkpoint_is_not_executed_twice(tmp_path, monkeypatch):
    async def scenario():
        h = Harness(tmp_path, monkeypatch)
        effects = []

        async def update(page_id: str, command: str, content: str):
            effects.append((page_id, content))
            return "added"

        h.catalog = [
            StructuredTool.from_function(coroutine=update, name="notion-update-page", description="Update page")
        ]
        h.outputs.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "notion-update-page",
                        "args": {"page_id": PAGE, "command": "insert_content", "content": "Note"},
                        "id": "add",
                    }
                ],
            )
        )
        await h.turn("Add the note")
        assert effects == [(PAGE, "Note")]
        snapshots = [
            snapshot async for snapshot in h.graph.aget_state_history({"configurable": {"thread_id": "thread"}})
        ]
        before_tools = next(snapshot for snapshot in snapshots if snapshot.next == ("tools",))
        await h.graph.ainvoke(None, before_tools.config)
        assert effects == [(PAGE, "Note")]

    asyncio.run(scenario())


def test_guardrail_structured_verdict_does_not_stream_into_chat(tmp_path, monkeypatch):
    from langchain_core.messages import HumanMessage

    from savant.semantic_approval import SemanticApprovalGuardrail

    async def scenario():
        def provider(request):
            assert json.loads(request.content)["text"]["format"]["type"] == "json_schema"
            return httpx.Response(
                200,
                json={
                    "id": "resp_guardrail",
                    "object": "response",
                    "created_at": 0,
                    "status": "completed",
                    "error": None,
                    "model": "test",
                    "output": [
                        {
                            "type": "message",
                            "id": "msg_guardrail",
                            "role": "assistant",
                            "status": "completed",
                            "content": [{"type": "output_text", "text": '{"decision":"APPROVE"}', "annotations": []}],
                        }
                    ],
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            model = ChatOpenAI(
                model="test",
                base_url="https://model.invalid/",
                api_key="synthetic",
                use_responses_api=True,
                output_version="responses/v1",
                disable_streaming=True,
                http_async_client=client,
            )
            h = Harness(tmp_path, monkeypatch)
            h.guardrail = SemanticApprovalGuardrail(model)
            h.rebuild()
            h.propose("page")
            await h.turn("Change page")
            chunks = []
            async for message, _ in h.graph.astream(
                {"messages": [HumanMessage(content="Oui", id="confirm")]},
                {"configurable": {"thread_id": "thread"}},
                stream_mode="messages",
            ):
                chunks.append(str(message.content))
            assert h.writes == [("page", "New")]
            assert all('"decision"' not in text for text in chunks)
            assert any("Done: I updated the page" in text for text in chunks)

    asyncio.run(scenario())
