"""The workspace routes and the chat's use of a stored session, with an in-memory store."""
import json

from fastapi.testclient import TestClient
import httpx
import pytest

from savant.bff_api import ApiSettings, add_api
from savant.oauth_callback import create_callback_app
from savant.workspace import WorkspaceService
from test_bff_api import AGENT_URL, OBJECT_ID, OWNER, OWNER_HEADERS, Credential, easy_auth, service  # noqa: F401
from workspace_fakes import InMemoryStore

SSE = ('data: {"type":"response.output_text.delta","delta":"Salut "}\n\n'
       'data: {"type":"response.output_text.delta","delta":"Ali"}\n\n'
       'data: {"type":"response.completed","response":{"id":"resp_9"}}\n\n')


def make(service, store=None, handler=None):
    sent = []

    def default(request):
        sent.append(json.loads(request.content))
        if sent[-1].get("stream"):
            return httpx.Response(200, content=SSE.encode(), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"id": "resp_9", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "Salut Ali"}]}]})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler or default))
    workspace = WorkspaceService(store or InMemoryStore())
    app = create_callback_app(service)
    add_api(app, ApiSettings(OWNER, AGENT_URL, owner_object_id=OBJECT_ID), service, Credential(), http,
            workspace=workspace)
    return TestClient(app), sent, workspace


@pytest.mark.parametrize("method,path", [
    ("get", "/api/projects"), ("post", "/api/projects"), ("patch", "/api/projects/x"), ("delete", "/api/projects/x"),
    ("get", "/api/sessions"), ("post", "/api/sessions"), ("patch", "/api/sessions/x"), ("delete", "/api/sessions/x"),
    ("get", "/api/sessions/x/messages"),
])
def test_workspace_routes_fail_closed(service, method, path):
    client, _, workspace = make(service)
    kwargs = {"json": {"name": "x", "projectId": "main", "title": "t"}} if method in ("post", "patch") else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401
    assert getattr(client, method)(path, headers=easy_auth("11111111-2222-4333-8444-555555555555"),
                                   **kwargs).status_code == 403
    assert workspace.store._projects == {} and workspace.store._sessions == {}


def test_the_workspace_routes_are_absent_without_storage(service):
    client = TestClient(create_callback_app(service))
    assert client.get("/api/projects", headers=OWNER_HEADERS).status_code == 404


def test_projects_and_sessions_round_trip_and_rules_map_to_statuses(service):
    client, _, _ = make(service)
    h = OWNER_HEADERS
    assert [p["id"] for p in client.get("/api/projects", headers=h).json()] == ["main"]
    assert client.post("/api/projects", headers=h, json={"id": "p1", "name": "Cloud"}).status_code == 201
    assert client.post("/api/projects", headers=h, json={"name": "cloud"}).status_code == 409
    assert client.patch("/api/projects/main", headers=h, json={"name": "X"}).status_code == 409
    assert client.delete("/api/projects/main", headers=h).status_code == 409
    assert client.post("/api/sessions", headers=h, json={"projectId": "ghost", "title": "t"}).status_code == 404
    created = client.post("/api/sessions", headers=h, json={"id": "s1", "projectId": "p1", "title": "Hello"})
    assert created.status_code == 201 and created.headers["cache-control"] == "no-store"
    moved = client.patch("/api/sessions/s1", headers=h, json={"projectId": "main", "pinned": True}).json()
    assert (moved["projectId"], moved["pinned"]) == ("main", True)
    assert [s["id"] for s in client.get("/api/sessions", headers=h, params={"project": "p1"}).json()] == []
    assert [s["id"] for s in client.get("/api/sessions", headers=h, params={"project": "main"}).json()] == ["s1"]
    assert client.patch("/api/sessions/s1", headers=h, json={"id": "other", "updatedAt": 1}).json()["id"] == "s1"
    assert client.get("/api/sessions/s1/messages", headers=h).json() == []
    assert client.delete("/api/sessions/s1", headers=h).status_code == 200
    assert client.get("/api/sessions/s1/messages", headers=h).status_code == 404
    assert client.post("/api/sessions", headers=h, json={"id": "../x", "projectId": "main", "title": "t"}).status_code == 422


def test_a_chat_with_a_session_sends_its_project_continues_its_thread_and_keeps_the_turn(service):
    client, sent, _ = make(service)
    h = OWNER_HEADERS
    client.post("/api/projects", headers=h, json={"id": "p1", "name": "Cloud"})
    client.post("/api/sessions", headers=h, json={"id": "s1", "projectId": "p1", "title": "Hello"})
    reply = client.post("/api/chat", headers=h, json={"message": "Bonjour", "session_id": "s1", "mode": "voice"})
    assert reply.json()["reply"] == "Salut Ali"
    assert sent[0] == {"input": "Bonjour", "stream": False, "metadata": {"channel": "voice", "project_id": "p1"}}
    client.post("/api/chat/stream", headers=h, json={"message": "Encore", "session_id": "s1"})
    # The second turn continues from the answer stored by the first, with no id from the browser.
    assert sent[1] == {"input": "Encore", "stream": True, "previous_response_id": "resp_9",
                       "metadata": {"project_id": "p1"}}
    texts = [(m["role"], m["text"]) for m in client.get("/api/sessions/s1/messages", headers=h).json()]
    assert texts == [("user", "Bonjour"), ("assistant", "Salut Ali"), ("user", "Encore"), ("assistant", "Salut Ali")]
    assert client.get("/api/sessions", headers=h).json()[0]["messageCount"] == 4


def test_a_chat_without_a_session_is_unchanged_and_an_unknown_session_is_refused(service):
    client, sent, workspace = make(service)
    h = OWNER_HEADERS
    client.post("/api/chat", headers=h, json={"message": "Salut", "conversation_id": "resp_1"})
    assert sent[0] == {"input": "Salut", "stream": False, "previous_response_id": "resp_1"}
    assert client.post("/api/chat", headers=h, json={"message": "x", "session_id": "ghost"}).status_code == 404
    assert len(sent) == 1 and workspace.store._messages == {}


def test_a_storage_failure_never_breaks_the_answer(service):
    class Broken(InMemoryStore):
        async def put_messages(self, session_id, messages):
            raise RuntimeError("cosmos down: secret detail")

    client, _, _ = make(service, Broken())
    h = OWNER_HEADERS
    client.post("/api/sessions", headers=h, json={"id": "s1", "projectId": "main", "title": "Hello"})
    assert client.post("/api/chat", headers=h, json={"message": "Bonjour", "session_id": "s1"}).json()["reply"] == "Salut Ali"
    body = client.post("/api/chat/stream", headers=h, json={"message": "Encore", "session_id": "s1"}).text
    assert '"type":"done"' in body and "secret" not in body
