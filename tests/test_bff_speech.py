"""The BFF's Speech token route: owner-only, Entra-minted, cached, never logged."""
import logging
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from savant.bff_api import SPEECH_SCOPE, ApiSettings, add_api
from savant.oauth_callback import create_callback_app
from test_bff_api import AGENT_URL, OBJECT_ID, OWNER, OWNER_HEADERS, easy_auth, service  # noqa: F401

SPEECH = "https://fp-x.cognitiveservices.azure.com"


class Credential:
    def __init__(self):
        self.scopes = []

    async def get_token(self, scope):
        self.scopes.append(scope)
        return SimpleNamespace(token="entra-token")

    async def close(self):
        pass


def client_for(service, handler, *, speech=True):
    calls = []

    def recording(request):
        calls.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(recording))
    credential = Credential()
    app = create_callback_app(service)
    settings = ApiSettings(OWNER, AGENT_URL, "", owner_object_id=OBJECT_ID,
                           speech_endpoint=SPEECH if speech else "", speech_region="italynorth" if speech else "")
    add_api(app, settings, service, credential, http)
    return TestClient(app), calls, credential


def test_owner_gets_a_cached_speech_token(service):
    client, calls, credential = client_for(service, lambda r: httpx.Response(200, text="speech-token"))
    first = client.post("/api/speech/token", headers=OWNER_HEADERS)
    second = client.post("/api/speech/token", headers=OWNER_HEADERS)
    assert first.status_code == 200 and first.json() == {"token": "speech-token", "region": "italynorth", "expires_in": 600}
    assert second.json()["token"] == "speech-token" and second.json()["expires_in"] <= 600
    assert len(calls) == 1 and str(calls[0].url) == SPEECH + "/sts/v1.0/issueToken"
    assert calls[0].headers["authorization"] == "Bearer entra-token" and credential.scopes == [SPEECH_SCOPE]
    assert first.headers["cache-control"] == "no-store"


def test_only_the_owner_gets_a_token(service):
    client, calls, _ = client_for(service, lambda r: httpx.Response(200, text="t"))
    assert client.post("/api/speech/token").status_code == 401
    assert client.post("/api/speech/token", headers=easy_auth("11111111-1111-4111-8111-111111111111")).status_code == 403
    assert calls == []


def test_voice_off_answers_404(service):
    client, calls, _ = client_for(service, lambda r: httpx.Response(200, text="t"), speech=False)
    assert client.post("/api/speech/token", headers=OWNER_HEADERS).status_code == 404 and calls == []


@pytest.mark.parametrize("response,status", [(httpx.Response(401, text="no"), 502), (httpx.Response(200, text=""), 502)])
def test_speech_failures_are_reported_without_the_token(service, caplog, response, status):
    client, _, _ = client_for(service, lambda r: response)
    with caplog.at_level(logging.WARNING, logger="savant.bff"):
        assert client.post("/api/speech/token", headers=OWNER_HEADERS).status_code == status
    assert "speech_token_failed" in caplog.text and "entra-token" not in caplog.text


@pytest.mark.parametrize("endpoint,region", [
    ("http://fp-x.cognitiveservices.azure.com", "italynorth"), ("https://evil.example.com", "italynorth"),
    ("https://fp-x.cognitiveservices.azure.com/path", "italynorth"), ("https://fp-x.cognitiveservices.azure.com", "Italy North"),
    ("https://fp-x.cognitiveservices.azure.com", ""), ("", "italynorth"),
])
def test_speech_settings_are_validated(monkeypatch, endpoint, region):
    monkeypatch.setenv("AGENT_RESPONSES_URL", AGENT_URL)
    monkeypatch.setenv("NOTION_OWNER_ID", OWNER)
    monkeypatch.setenv("BFF_OWNER_OBJECT_ID", OBJECT_ID)
    monkeypatch.setenv("SPEECH_ENDPOINT", endpoint)
    monkeypatch.setenv("SPEECH_REGION", region)
    with pytest.raises(RuntimeError):
        ApiSettings.from_env()


def test_speech_settings_are_read(monkeypatch):
    monkeypatch.setenv("AGENT_RESPONSES_URL", AGENT_URL)
    monkeypatch.setenv("NOTION_OWNER_ID", OWNER)
    monkeypatch.setenv("BFF_OWNER_OBJECT_ID", OBJECT_ID)
    monkeypatch.setenv("SPEECH_ENDPOINT", SPEECH + "/")
    monkeypatch.setenv("SPEECH_REGION", "ItalyNorth")
    settings = ApiSettings.from_env()
    assert settings.speech_endpoint == SPEECH and settings.speech_region == "italynorth"
