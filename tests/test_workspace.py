import asyncio

import pytest

from savant.workspace import MAIN_ID, WorkspaceError, WorkspaceService
from workspace_fakes import InMemoryStore


def run(scenario):
    async def main():
        service = WorkspaceService(InMemoryStore())
        return await scenario(service)
    return asyncio.run(main())


def fails(kind, coroutine):
    async def check():
        with pytest.raises(WorkspaceError) as caught:
            await coroutine
        assert caught.value.kind == kind
    return check()


def test_main_always_exists_and_cannot_be_renamed_or_deleted():
    async def scenario(w):
        assert [p["id"] for p in await w.projects()] == [MAIN_ID]
        await fails("protected", w.delete_project(MAIN_ID))
        await fails("protected", w.update_project(MAIN_ID, "Other", None))
        assert (await w.update_project(MAIN_ID, None, "#e0699b"))["color"] == "#e0699b"
    run(scenario)


def test_project_names_are_unique_ignoring_case_and_spacing():
    async def scenario(w):
        await w.create_project(None, "Cloud study", None)
        await fails("conflict", w.create_project(None, "  cloud   STUDY ", None))
        await fails("conflict", w.create_project(None, "main", None))
        other = await w.create_project(None, "Notes", None)
        await fails("conflict", w.update_project(other["id"], "cloud study", None))
        await fails("invalid", w.create_project(None, "x" * 41, None))
        await fails("invalid", w.create_project(None, "   ", None))
        await fails("invalid", w.create_project(None, "Fine", "red"))
    run(scenario)


def test_a_session_needs_a_known_project_and_can_move():
    async def scenario(w):
        await fails("not_found", w.create_session(None, "ghost", "Hello"))
        other = await w.create_project(None, "Other", None)
        s = await w.create_session("s1", MAIN_ID, "Hello")
        moved = await w.update_session("s1", {"projectId": other["id"], "title": " New  title ", "pinned": True})
        assert (moved["projectId"], moved["title"], moved["pinned"]) == (other["id"], "New title", True)
        await fails("not_found", w.update_session("s1", {"projectId": "ghost"}))
        await fails("conflict", w.create_session("s1", MAIN_ID, "Again"))
        await fails("invalid", w.create_session("../x", MAIN_ID, "Bad id"))
        assert s["messageCount"] == 0
    run(scenario)


def test_recording_a_turn_keeps_text_and_the_thread_id_and_resumes_after_reload():
    async def scenario(w):
        await w.create_session("s1", MAIN_ID, "Hello")
        await w.record_turn("s1", "Bonjour", "Salut !", voice=True, response_id="resp_1")
        session = await w.session("s1")
        assert (session["messageCount"], session["conversationId"]) == (2, "resp_1")
        messages = await w.messages("s1")
        assert [(m["role"], m["text"], m.get("voice")) for m in messages] == [
            ("user", "Bonjour", True), ("assistant", "Salut !", True)]
        await w.record_turn("s1", "Encore", "Oui", voice=False, response_id=None)
        assert (await w.session("s1"))["conversationId"] == "resp_1"  # kept when no new id came back
        assert len(await w.messages("s1")) == 4
    run(scenario)


def test_two_projects_never_see_each_others_sessions_and_deleting_one_leaves_the_other():
    async def scenario(w):
        a = await w.create_project("pa", "Alpha", None)
        b = await w.create_project("pb", "Beta", None)
        await w.create_session("sa", a["id"], "In alpha")
        await w.create_session("sb", b["id"], "In beta")
        await w.record_turn("sa", "alpha question", "alpha answer", voice=False, response_id="ra")
        await w.record_turn("sb", "beta question", "beta answer", voice=False, response_id="rb")
        assert [s["id"] for s in await w.sessions(a["id"])] == ["sa"]
        assert [s["id"] for s in await w.sessions(b["id"])] == ["sb"]
        await w.delete_project(a["id"])
        assert [s["id"] for s in await w.sessions()] == ["sb"]
        await fails("not_found", w.messages("sa"))
        assert [m["text"] for m in await w.messages("sb")] == ["beta question", "beta answer"]
    run(scenario)


def test_deleting_a_session_deletes_its_messages_and_unknown_ones_are_not_found():
    async def scenario(w):
        await w.create_session("s1", MAIN_ID, "Hello")
        await w.record_turn("s1", "q", "a", voice=False, response_id=None)
        await w.delete_session("s1")
        assert w.store._messages == {}
        await fails("not_found", w.delete_session("s1"))
    run(scenario)
