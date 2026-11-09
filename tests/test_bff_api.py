import asyncio
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import httpx
import pytest

from savant.bff_api import AGENT_TIMEOUT_SECONDS, WARMUP_EXPECTED, WARMUP_PROMPT, ApiSettings, add_api
from savant.health import RUNTIME_SMOKE_EXPECTED, RUNTIME_SMOKE_PROMPT
from savant.notion_oauth import NotionOAuth, SQLiteOAuthStore
from savant.oauth_callback import create_callback_app

CALLBACK = "https://app.example/oauth/notion/callback"
AGENT_URL = "https://acct.services.ai.azure.com/api/projects/p/agents/a/endpoint/protocols/openai/responses"
OWNER = "owner-platform-id"
OBJECT_ID = "0b1c2d3e-4f50-4a61-8b72-9c83d4e5f607"


def easy_auth(object_id=OBJECT_ID, idp="aad"):
    """Headers Container Apps authentication injects after validating an Entra token."""
    headers = {"x-ms-client-principal-id": object_id}
    if idp is not None:
        headers["x-ms-client-principal-idp"] = idp
    return headers


OWNER_HEADERS = easy_auth()


class Credential:
    closed = False

    async def get_token(self, scope):
        assert scope == "https://ai.azure.com/.default"
        return SimpleNamespace(token="agent-token")

    async def close(self):
        self.closed = True


@pytest.fixture
def service(tmp_path):
    store = SQLiteOAuthStore(str(tmp_path / "oauth.db"), Fernet.generate_key().decode())

    async def seed():
        async with store.transaction() as data:
            data["client"] = {"callback_url": CALLBACK, "client_id": "id",
                              "authorization_endpoint": "https://mcp.notion.com/authorize",
                              "token_endpoint": "https://mcp.notion.com/token"}
    asyncio.run(seed())
    return NotionOAuth(CALLBACK, store)


def make_client(service, handler=None, origin="", credential=None):
    sent = []

    def default(request):
        sent.append(request)
        return httpx.Response(200, json={"id": "resp_2", "output": [
            {"type": "reasoning", "content": [{"type": "output_text", "text": "hidden"}]},
            {"type": "message", "content": [{"type": "output_text", "text": "Bonjour "},
                                            {"type": "output_text", "text": "Ali"}]}]})

    def recording(request):
        sent.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(recording if handler else default))
    credential = credential or Credential()
    app = create_callback_app(service)
    add_api(app, ApiSettings(OWNER, AGENT_URL, origin, owner_object_id=OBJECT_ID), service, credential, http)
    return TestClient(app), sent


@pytest.mark.parametrize("method,path", [
    ("get", "/oauth/notion/start"), ("get", "/api/oauth/notion/start"),
    ("get", "/oauth/notion/status"), ("get", "/api/oauth/notion/status"),
    ("post", "/api/chat"), ("post", "/api/chat/stream"), ("post", "/api/warmup"),
])
def test_every_owner_route_fails_closed(service, method, path):
    client, sent = make_client(service)
    kwargs = {"json": {"message": "salut"}} if method == "post" else {}
    assert getattr(client, method)(path, follow_redirects=False, **kwargs).status_code == 401
    # Header present but empty, or the old Static Web Apps principal alone: still no identity.
    for headers in ({"x-ms-client-principal-id": " "}, {"x-ms-client-principal": "eyJ1c2VyUm9sZXMiOlsib3duZXIiXX0="}):
        assert getattr(client, method)(path, headers=headers, follow_redirects=False, **kwargs).status_code == 401
    for headers in (easy_auth("11111111-2222-4333-8444-555555555555"), easy_auth(idp="google"),
                    easy_auth(idp=None), easy_auth(OBJECT_ID[:-1]),
                    {"x-ms-client-principal-id": ("é" + OBJECT_ID).encode("latin-1"), "x-ms-client-principal-idp": "aad"}):
        assert getattr(client, method)(path, headers=headers, follow_redirects=False, **kwargs).status_code == 403
    assert sent == []


def test_owner_object_id_is_matched_case_insensitively(service):
    client, _ = make_client(service)
    assert client.get("/api/oauth/notion/status", headers=easy_auth(OBJECT_ID.upper())).status_code == 200


def test_callback_and_readiness_stay_public_with_api_enabled(service):
    client, _ = make_client(service)
    assert client.get("/readiness").json() == {"status": "ready"}
    assert client.get("/oauth/notion/callback", params={"state": "unknown"}).status_code == 400


def test_api_is_absent_when_not_configured(service):
    client = TestClient(create_callback_app(service))
    assert client.post("/api/chat", json={"message": "x"}, headers=OWNER_HEADERS).status_code == 404
    assert client.get("/api/oauth/notion/start", headers=OWNER_HEADERS).status_code == 404


@pytest.mark.parametrize("path", ["/oauth/notion/start", "/api/oauth/notion/start"])
def test_start_redirects_to_notion_for_the_fixed_owner_only(service, path):
    client, _ = make_client(service)
    response = client.get(path, params={"user_id": "mallory", "user": "mallory"},
                          headers=OWNER_HEADERS, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["cache-control"] == "no-store"
    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == "https://mcp.notion.com/authorize"
    assert parse_qs(location.query)["redirect_uri"] == [CALLBACK]

    async def pending_users():
        async with service.store.transaction() as data:
            return {flow["user"] for flow in data["pending"].values()}
    assert asyncio.run(pending_users()) == {service._user(OWNER)}
    # A second click reuses the pending consent instead of piling up flows.
    again = client.get(path, headers=OWNER_HEADERS, follow_redirects=False)
    assert again.headers["location"] == response.headers["location"]


def test_status_follows_the_grant_stored_for_the_fixed_owner(service):
    client, _ = make_client(service)
    assert client.get("/api/oauth/notion/status", headers=OWNER_HEADERS).json() == {"connected": False}

    async def grant(user):
        async with service.store.transaction() as data:
            data.setdefault("tokens", {})[service._user(user)] = {
                "access_token": "secret", "refresh_token": None, "expires_at": service.clock() + 3600}
    asyncio.run(grant("someone-else"))
    assert client.get("/api/oauth/notion/status", headers=OWNER_HEADERS).json() == {"connected": False}
    asyncio.run(grant(OWNER))
    response = client.get("/api/oauth/notion/status", headers=OWNER_HEADERS)
    assert response.json() == {"connected": True}
    assert response.headers["cache-control"] == "no-store"
    assert "secret" not in response.text


def test_chat_relays_to_the_agent_and_returns_the_next_conversation_id(service):
    credential = Credential()
    client, sent = make_client(service, credential=credential)
    response = client.post("/api/chat", headers=OWNER_HEADERS,
                           json={"message": "Salut", "conversation_id": "resp_1",
                                 "user_id": "mallory", "stream": True, "model": "other"})
    assert response.status_code == 200
    assert response.json() == {"conversation_id": "resp_2", "reply": "Bonjour Ali"}
    assert response.headers["cache-control"] == "no-store"
    (request,) = sent
    assert str(request.url) == AGENT_URL
    assert request.headers["authorization"] == "Bearer agent-token"
    assert json.loads(request.content) == {"input": "Salut", "stream": False, "previous_response_id": "resp_1"}

    client.post("/api/chat", headers=OWNER_HEADERS, json={"message": "Premier message"})
    assert json.loads(sent[1].content) == {"input": "Premier message", "stream": False}


@pytest.mark.parametrize("body", [{}, {"message": ""}, {"message": "x" * 8001},
                                  {"message": "x", "conversation_id": "bad id/../"}, {"message": 3}])
def test_chat_rejects_invalid_input_before_calling_the_agent(service, body):
    client, sent = make_client(service)
    assert client.post("/api/chat", headers=OWNER_HEADERS, json=body).status_code == 422
    assert sent == []


@pytest.mark.parametrize("handler,status", [
    (lambda request: httpx.Response(500, text="secret upstream detail"), 502),
    (lambda request: httpx.Response(200, json={"output": []}), 502),
    (lambda request: httpx.Response(200, text="not json"), 502),
    (lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), 504),
])
def test_chat_maps_agent_failures_without_leaking_details(service, handler, status):
    client, _ = make_client(service, handler)
    response = client.post("/api/chat", headers=OWNER_HEADERS, json={"message": "Salut"})
    assert response.status_code == status
    assert "secret" not in response.text and "slow" not in response.text


def test_cors_only_allows_the_configured_pwa_origin(service):
    client, _ = make_client(service, origin="http://localhost:5173")
    preflight = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
    allowed = client.options("/api/chat", headers={"Origin": "http://localhost:5173", **preflight})
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    denied = client.options("/api/chat", headers={"Origin": "https://evil.example", **preflight})
    assert "access-control-allow-origin" not in denied.headers
    plain, _ = make_client(service)
    assert "access-control-allow-origin" not in plain.options(
        "/api/chat", headers={"Origin": "http://localhost:5173", **preflight}).headers


def test_credential_is_closed_with_the_app(service):
    credential = Credential()
    app = create_callback_app(service, (ApiSettings(OWNER, AGENT_URL, owner_object_id=OBJECT_ID), credential))
    with TestClient(app) as client:
        assert client.get("/readiness").status_code == 200
    assert credential.closed


def test_settings_enable_the_api_only_with_an_agent_url(monkeypatch):
    for name in ("NOTION_OWNER_ID", "AGENT_RESPONSES_URL", "PWA_ORIGIN", "BFF_OWNER_OBJECT_ID"):
        monkeypatch.delenv(name, raising=False)
    assert ApiSettings.from_env() is None
    # An existing callback-only BFF already has the owner id: it must keep starting.
    monkeypatch.setenv("NOTION_OWNER_ID", OWNER)
    assert ApiSettings.from_env() is None
    monkeypatch.setenv("AGENT_RESPONSES_URL", AGENT_URL)
    with pytest.raises(RuntimeError, match="BFF_OWNER_OBJECT_ID"):
        ApiSettings.from_env()
    monkeypatch.setenv("BFF_OWNER_OBJECT_ID", OBJECT_ID.upper())
    assert ApiSettings.from_env() == ApiSettings(OWNER, AGENT_URL + "?api-version=v1", "", owner_object_id=OBJECT_ID)
    monkeypatch.setenv("PWA_ORIGIN", "http://localhost:5173")
    assert ApiSettings.from_env().pwa_origin == "http://localhost:5173"
    monkeypatch.delenv("NOTION_OWNER_ID")
    with pytest.raises(RuntimeError, match="NOTION_OWNER_ID"):
        ApiSettings.from_env()


@pytest.mark.parametrize("value", ["", "not-a-guid", OBJECT_ID.replace("-", ""), "{" + OBJECT_ID + "}", OBJECT_ID + "0"])
def test_settings_require_a_well_formed_entra_object_id(monkeypatch, value):
    monkeypatch.setenv("NOTION_OWNER_ID", OWNER)
    monkeypatch.setenv("AGENT_RESPONSES_URL", AGENT_URL)
    monkeypatch.setenv("BFF_OWNER_OBJECT_ID", value)
    with pytest.raises(RuntimeError, match="BFF_OWNER_OBJECT_ID"):
        ApiSettings.from_env()


@pytest.mark.parametrize("name,value", [
    ("AGENT_RESPONSES_URL", "http://acct.services.ai.azure.com/responses"),
    ("AGENT_RESPONSES_URL", "https://evil.example/responses"),
    ("AGENT_RESPONSES_URL", "https://user:pw@acct.services.ai.azure.com/responses"),
    ("PWA_ORIGIN", "http://pwa.example"),
    ("PWA_ORIGIN", "https://pwa.example/path"),
])
def test_settings_reject_unsafe_urls(monkeypatch, name, value):
    monkeypatch.setenv("NOTION_OWNER_ID", OWNER)
    monkeypatch.setenv("AGENT_RESPONSES_URL", AGENT_URL)
    monkeypatch.setenv("BFF_OWNER_OBJECT_ID", OBJECT_ID)
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError):
        ApiSettings.from_env()


@pytest.mark.parametrize("configured,expected", [
    (AGENT_URL, AGENT_URL + "?api-version=v1"),
    (AGENT_URL + "?api-version=2025-01-01", AGENT_URL + "?api-version=2025-01-01"),
    (AGENT_URL + "?foo=1", AGENT_URL + "?foo=1&api-version=v1"),
    (AGENT_URL + "?API-Version=2025-01-01&foo=1", AGENT_URL + "?API-Version=2025-01-01&foo=1"),
])
def test_settings_add_the_agent_api_version_only_when_missing(monkeypatch, configured, expected):
    monkeypatch.setenv("NOTION_OWNER_ID", OWNER)
    monkeypatch.setenv("BFF_OWNER_OBJECT_ID", OBJECT_ID)
    monkeypatch.setenv("AGENT_RESPONSES_URL", configured)
    assert ApiSettings.from_env().agent_responses_url == expected


def _app_from_env(service, monkeypatch, handler):
    monkeypatch.setenv("NOTION_OWNER_ID", OWNER)
    monkeypatch.setenv("BFF_OWNER_OBJECT_ID", OBJECT_ID)
    monkeypatch.setenv("AGENT_RESPONSES_URL", AGENT_URL)
    sent = []

    def recording(request):
        sent.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(recording))
    app = create_callback_app(service)
    add_api(app, ApiSettings.from_env(), service, Credential(), http)
    return TestClient(app), sent


def test_relay_timeout_covers_a_slow_notion_read_but_stays_under_the_ingress_default():
    # Measured: 66 s for one Notion read; Container Apps ingress request timeout default: 240 s.
    assert 66 < AGENT_TIMEOUT_SECONDS < 240


def test_chat_posts_to_the_agent_with_the_api_version(service, monkeypatch):
    client, sent = _app_from_env(service, monkeypatch, lambda request: httpx.Response(200, json={"id": "resp_9", "output": []}))
    assert client.post("/api/chat", headers=OWNER_HEADERS, json={"message": "Salut"}).status_code == 200
    assert sent[0].url.params["api-version"] == "v1"
    assert sent[0].url.path.endswith("/openai/responses")


def test_agent_http_error_is_logged_with_its_status_only(service, monkeypatch, caplog):
    secret = "synthetic-agent-body-secret"
    client, _ = _app_from_env(service, monkeypatch, lambda request: httpx.Response(400, text=secret))
    with caplog.at_level("WARNING", logger="savant.bff"):
        response = client.post("/api/chat", headers=OWNER_HEADERS, json={"message": "Salut"})
    assert response.status_code == 502
    assert secret not in response.text
    records = [record for record in caplog.records if record.name == "savant.bff"]
    assert [(record.msg, record.agent_status) for record in records] == [("chat_relay_failed", 400)]
    assert secret not in " ".join(str(vars(record)) for record in records)


def test_unexpected_relay_error_is_logged_by_exception_type_only(service, monkeypatch, caplog):
    def broken(request):
        raise httpx.ConnectError("synthetic-connect-secret")

    client, _ = _app_from_env(service, monkeypatch, broken)
    with caplog.at_level("WARNING", logger="savant.bff"):
        response = client.post("/api/chat", headers=OWNER_HEADERS, json={"message": "Salut"})
    assert response.status_code == 502
    records = [record for record in caplog.records if record.name == "savant.bff"]
    assert [(record.msg, record.error_type) for record in records] == [("chat_relay_failed", "ConnectError")]
    assert "synthetic-connect-secret" not in " ".join(str(vars(record)) for record in records)


def agent_stream(*events):
    """What the agent's Responses host sends: one `event:` and one `data:` line per event."""
    body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
    return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})


def read_events(response):
    return [json.loads(chunk[len("data: "):]) for chunk in response.text.split("\n\n") if chunk]


def test_stream_forwards_text_tool_names_and_the_next_conversation_id(service):
    client, sent = make_client(service, lambda request: agent_stream(
        {"type": "response.created", "response": {"id": "resp_9"}},
        {"type": "response.output_item.added", "item": {"type": "reasoning", "summary": [{"text": "private thoughts"}]}},
        {"type": "response.output_item.added", "item": {"type": "function_call", "id": "fc_1", "call_id": "call_1",
                                                         "name": "notion-search", "arguments": "{\"query\": \"secret\"}"}},
        {"type": "response.function_call_arguments.delta", "delta": "{\"query\": \"secret\"}"},
        {"type": "response.output_item.done", "item": {"type": "function_call_output", "call_id": "call_1",
                                                        "output": "private notion page"}},
        {"type": "response.output_text.delta", "delta": "Bonjour "},
        {"type": "response.output_text.delta", "delta": "Ali"},
        {"type": "response.completed", "response": {"id": "resp_9", "output": []}}))
    response = client.post("/api/chat/stream", headers=OWNER_HEADERS,
                           json={"message": "Salut", "conversation_id": "resp_1", "model": "other"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "no-store" in response.headers["cache-control"]
    assert read_events(response) == [
        {"type": "tool", "id": "call_1", "name": "notion-search", "status": "running"},
        {"type": "tool", "id": "call_1", "status": "done"},
        {"type": "delta", "text": "Bonjour "},
        {"type": "delta", "text": "Ali"},
        {"type": "done", "conversation_id": "resp_9"},
    ]
    for private in ("private thoughts", "secret", "private notion page"):
        assert private not in response.text
    (request,) = sent
    assert request.headers["authorization"] == "Bearer agent-token"
    assert json.loads(request.content) == {"input": "Salut", "stream": True, "previous_response_id": "resp_1"}


def test_stream_sanitizes_names_and_ids_it_relays(service):
    client, _ = make_client(service, lambda request: agent_stream(
        {"type": "response.output_item.added", "item": {"type": "function_call", "call_id": "call_2", "name": "bad name\n!"}},
        {"type": "response.output_item.added", "item": {"type": "function_call", "call_id": "x y", "name": "ok"}},
        {"type": "response.completed", "response": {"id": "resp 9"}}))
    events = read_events(client.post("/api/chat/stream", headers=OWNER_HEADERS, json={"message": "Salut"}))
    assert events[0] == {"type": "tool", "id": "call_2", "name": "tool", "status": "running"}
    # An unusable id never reaches the PWA, and a stream with no valid end is reported as a failure.
    assert events[-1] == {"type": "error", "kind": "upstream"}
    assert len(events) == 2


def test_stream_reports_an_agent_that_stops_without_finishing(service):
    client, _ = make_client(service, lambda request: agent_stream(
        {"type": "response.output_text.delta", "delta": "Bon"}))
    assert read_events(client.post("/api/chat/stream", headers=OWNER_HEADERS, json={"message": "Salut"})) == [
        {"type": "delta", "text": "Bon"}, {"type": "error", "kind": "upstream"}]


def test_stream_forwards_an_agent_failure_event(service):
    client, _ = make_client(service, lambda request: agent_stream({"type": "response.failed", "response": {}}))
    assert read_events(client.post("/api/chat/stream", headers=OWNER_HEADERS, json={"message": "Salut"})) == [
        {"type": "error", "kind": "upstream"}]


@pytest.mark.parametrize("handler,status", [
    (lambda request: httpx.Response(500, text="secret upstream detail"), 502),
    (lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), 504),
    (lambda request: (_ for _ in ()).throw(httpx.ConnectError("secret connect detail")), 502),
])
def test_stream_maps_agent_failures_before_streaming_without_leaking_details(service, handler, status):
    client, _ = make_client(service, handler)
    response = client.post("/api/chat/stream", headers=OWNER_HEADERS, json={"message": "Salut"})
    assert response.status_code == status
    assert "secret" not in response.text and "slow" not in response.text


def test_stream_rejects_invalid_input_before_calling_the_agent(service):
    client, sent = make_client(service)
    assert client.post("/api/chat/stream", headers=OWNER_HEADERS, json={"message": ""}).status_code == 422
    assert sent == []


def test_stream_failure_is_logged_without_the_agent_body(service, caplog):
    client, _ = make_client(service, lambda request: httpx.Response(400, text="synthetic-agent-body-secret"))
    with caplog.at_level("WARNING", logger="savant.bff"):
        assert client.post("/api/chat/stream", headers=OWNER_HEADERS, json={"message": "Salut"}).status_code == 502
    records = [record for record in caplog.records if record.name == "savant.bff"]
    assert [(record.msg, record.agent_status) for record in records] == [("chat_relay_failed", 400)]


def test_warmup_sends_the_tool_free_probe_and_reports_readiness(service):
    client, sent = make_client(service, lambda request: httpx.Response(200, json={"id": "resp_3", "output": [
        {"type": "message", "content": [{"type": "output_text", "text": WARMUP_EXPECTED}]}]}))
    response = client.post("/api/warmup", headers=OWNER_HEADERS)
    assert response.status_code == 200
    # The warm conversation is handed over so the next first message reuses its session.
    assert response.json() == {"ready": True, "conversation_id": "resp_3"}
    assert response.headers["cache-control"] == "no-store"
    assert json.loads(sent[0].content) == {"input": WARMUP_PROMPT, "stream": False}


def test_warmup_is_not_ready_when_the_agent_answers_something_else(service):
    client, _ = make_client(service)
    assert client.post("/api/warmup", headers=OWNER_HEADERS).json() == {"ready": False}


@pytest.mark.parametrize("handler,status", [
    (lambda request: httpx.Response(500, text="secret upstream detail"), 502),
    (lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), 504),
])
def test_warmup_maps_agent_failures_without_leaking_details(service, handler, status):
    client, _ = make_client(service, handler)
    response = client.post("/api/warmup", headers=OWNER_HEADERS)
    assert response.status_code == status
    assert "secret" not in response.text and "slow" not in response.text


def test_warmup_probe_matches_the_agent_runtime_probe():
    # The BFF image does not ship savant.health, so the text is duplicated: it must not drift.
    assert (WARMUP_PROMPT, WARMUP_EXPECTED) == (RUNTIME_SMOKE_PROMPT, RUNTIME_SMOKE_EXPECTED)


def test_stream_labels_a_toolbox_dispatch_with_the_inner_tool_name_only(service):
    client, _ = make_client(service, lambda request: agent_stream(
        {"type": "response.output_item.added", "item": {"type": "function_call", "call_id": "call_3", "name": "call_tool"}},
        {"type": "response.output_item.done", "item": {"type": "function_call", "call_id": "call_3", "name": "call_tool",
         "arguments": "{\"name\": \"outlook-sa2___outlook_GetEmails\", \"arguments\": {\"searchQuery\": \"secret\"}}"}},
        {"type": "response.output_item.done", "item": {"type": "function_call", "call_id": "call_4", "name": "call_tool",
         "arguments": "{\"name\": \"bad name!\", \"arguments\": {}}"}},
        {"type": "response.output_item.done", "item": {"type": "function_call", "call_id": "call_5", "name": "call_tool",
         "arguments": "not json"}},
        {"type": "response.completed", "response": {"id": "resp_3"}}))
    response = client.post("/api/chat/stream", headers=OWNER_HEADERS, json={"message": "Mail?"})
    assert read_events(response) == [
        {"type": "tool", "id": "call_3", "name": "call_tool", "status": "running"},
        {"type": "tool", "id": "call_3", "name": "outlook-sa2___outlook_GetEmails", "status": "running"},
        {"type": "done", "conversation_id": "resp_3"},
    ]
    assert "secret" not in response.text


def test_stream_flags_a_sign_in_answer_without_relaying_the_link(service):
    link = "https://logic-italynorth-001.consent.azure-apihub.net/login?data=SECRET"
    client, _ = make_client(service, lambda request: agent_stream(
        {"type": "response.output_item.added", "item": {"type": "function_call", "call_id": "call_6", "name": "call_tool"}},
        {"type": "response.output_item.done", "item": {"type": "function_call_output", "call_id": "call_6", "output": link}},
        {"type": "response.output_item.done", "item": {"type": "function_call_output", "call_id": "call_7", "output": "[]"}},
        {"type": "response.completed", "response": {"id": "resp_6"}}))
    response = client.post("/api/chat/stream", headers=OWNER_HEADERS, json={"message": "Mail?"})
    assert read_events(response) == [
        {"type": "tool", "id": "call_6", "name": "call_tool", "status": "running"},
        {"type": "tool", "id": "call_6", "status": "done", "consent": True},
        {"type": "tool", "id": "call_7", "status": "done"},
        {"type": "done", "conversation_id": "resp_6"},
    ]
    assert "SECRET" not in response.text and "azure-apihub" not in response.text


def test_voice_mode_is_relayed_as_responses_metadata_on_both_chat_routes(service):
    client, sent = make_client(service)
    client.post("/api/chat", headers=OWNER_HEADERS, json={"message": "Météo ?", "mode": "voice"})
    assert json.loads(sent[0].content) == {"input": "Météo ?", "stream": False, "metadata": {"channel": "voice"}}
    client.post("/api/chat", headers=OWNER_HEADERS, json={"message": "Météo ?", "mode": "text"})
    assert json.loads(sent[1].content) == {"input": "Météo ?", "stream": False}
    assert client.post("/api/chat", headers=OWNER_HEADERS, json={"message": "x", "mode": "shout"}).status_code == 422
    assert len(sent) == 2

    client, sent = make_client(service, lambda request: agent_stream(
        {"type": "response.completed", "response": {"id": "resp_3", "output": []}}))
    client.post("/api/chat/stream", headers=OWNER_HEADERS,
                json={"message": "Météo ?", "conversation_id": "resp_1", "mode": "voice"})
    assert json.loads(sent[0].content) == {"input": "Météo ?", "stream": True, "previous_response_id": "resp_1",
                                           "metadata": {"channel": "voice"}}
