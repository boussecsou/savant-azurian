import asyncio
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet

from savant.notion_oauth import NotionOAuth, OAuthError, SQLiteOAuthStore
from savant.oauth_callback import create_callback_app


def test_oauth_roundtrip_rotation_isolation_and_restart(tmp_path):
    async def scenario():
        clock = [1000]
        calls = []
        invalid = [False]

        def handler(request):
            calls.append(request)
            if request.url.path.endswith("oauth-authorization-server"):
                return httpx.Response(
                    200,
                    json={
                        "authorization_endpoint": "https://mcp.notion.com/authorize",
                        "token_endpoint": "https://mcp.notion.com/token",
                        "registration_endpoint": "https://mcp.notion.com/register",
                        "code_challenge_methods_supported": ["S256"],
                    },
                )
            if request.url.path == "/register":
                return httpx.Response(201, json={"client_id": "registered"})
            form = parse_qs(request.content.decode())
            if form["grant_type"] == ["authorization_code"]:
                assert len(form["code_verifier"][0]) >= 43
                return httpx.Response(
                    200, json={"access_token": "secret1", "refresh_token": "refresh1", "expires_in": 120}
                )
            if invalid[0]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            assert form["refresh_token"] == ["refresh1"]
            return httpx.Response(200, json={"access_token": "secret2", "refresh_token": "refresh2", "expires_in": 120})

        key = Fernet.generate_key().decode()
        path = str(tmp_path / "oauth.db")
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        service = NotionOAuth(
            "https://app.example/oauth/notion/callback", SQLiteOAuthStore(path, key), client, lambda: clock[0]
        )
        url = await service.begin("alice")
        assert await service.begin("alice") == url
        assert await service.begin("bob") != url
        state = parse_qs(urlsplit(url).query)["state"][0]
        assert parse_qs(urlsplit(url).query)["code_challenge_method"] == ["S256"]
        await service.finish(state, "code")
        assert await service.get_access_token("alice") == "secret1"
        assert await service.get_access_token("bob") is None
        with pytest.raises(OAuthError):
            await service.finish(state, "replayed")
        assert b"secret1" not in (tmp_path / "oauth.db").read_bytes()
        restarted = NotionOAuth(service.callback_url, SQLiteOAuthStore(path, key), client, lambda: clock[0])
        clock[0] += 70
        assert await restarted.get_access_token("alice") == "secret2"
        async with restarted.store.transaction() as data:
            assert data["tokens"][service._user("alice")]["refresh_token"] == "refresh2"
        invalid[0] = True
        clock[0] += 70
        assert await restarted.get_access_token("alice") is None
        assert len([r for r in calls if r.url.path == "/register"]) == 1
        await client.aclose()

    asyncio.run(scenario())


def test_expiry_denial_and_callback_html_do_not_expose_values(tmp_path):
    async def scenario():
        store = SQLiteOAuthStore(str(tmp_path / "oauth.db"), Fernet.generate_key().decode())
        async with store.transaction() as data:
            data["client"] = {
                "callback_url": "https://app.example/oauth/notion/callback",
                "client_id": "id",
                "authorization_endpoint": "https://mcp.notion.com/authorize",
                "token_endpoint": "https://mcp.notion.com/token",
            }
        now = [1000]
        service = NotionOAuth("https://app.example/oauth/notion/callback", store, clock=lambda: now[0])
        first = parse_qs(urlsplit(await service.begin("alice")).query)["state"][0]
        now[0] += 601
        with pytest.raises(OAuthError, match="expired"):
            await service.finish(first, "code")
        second = parse_qs(urlsplit(await service.begin("alice")).query)["state"][0]
        with pytest.raises(OAuthError, match="declined"):
            await service.finish(second, error="private provider data")
        with pytest.raises(OAuthError, match="expired"):
            await service.finish(second, "code")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_callback_app(service)), base_url="https://app.example"
        ) as client:
            response = await client.get("/oauth/notion/callback?state=secret-state&code=secret-code&error=secret-error")
        assert response.status_code == 400
        assert "secret-" not in response.text
        assert response.headers["cache-control"] == "no-store"

    asyncio.run(scenario())


def test_requires_identity_and_safe_callback(tmp_path):
    store = SQLiteOAuthStore(str(tmp_path / "oauth.db"), Fernet.generate_key().decode())
    with pytest.raises(ValueError):
        NotionOAuth("http://public.example/callback", store)
    service = NotionOAuth("http://localhost:8000/oauth/notion/callback", store)
    with pytest.raises(OAuthError, match="identity"):
        asyncio.run(service.begin(""))


@pytest.mark.parametrize(
    "registration",
    [
        {"client_id": "id", "token_endpoint_auth_method": "client_secret_basic"},
        {"client_id": "id", "redirect_uris": ["https://attacker.example/callback"]},
    ],
)
def test_rejects_substituted_client_configuration(tmp_path, registration):
    async def scenario():
        def handler(request):
            if request.url.path == "/register":
                return httpx.Response(201, json=registration)
            return httpx.Response(
                200,
                json={
                    "authorization_endpoint": "https://mcp.notion.com/authorize",
                    "token_endpoint": "https://mcp.notion.com/token",
                    "registration_endpoint": "https://mcp.notion.com/register",
                    "code_challenge_methods_supported": ["S256"],
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = NotionOAuth(
                "https://app.example/oauth/notion/callback",
                SQLiteOAuthStore(str(tmp_path / "oauth.db"), Fernet.generate_key().decode()),
                client,
            )
            with pytest.raises(OAuthError):
                await service.begin("alice")

    asyncio.run(scenario())


@pytest.mark.parametrize("lifetime", [float("nan"), float("inf"), -1, 0, "invalid"])
def test_rejects_invalid_token_lifetime(tmp_path, lifetime):
    service = NotionOAuth(
        "http://localhost:8000/oauth/notion/callback",
        SQLiteOAuthStore(str(tmp_path / "oauth.db"), Fernet.generate_key().decode()),
    )
    with pytest.raises(OAuthError):
        service._tokens({"access_token": "secret", "expires_in": lifetime})


def test_blob_serializes_refresh_across_instances_and_releases_on_failure():
    from azure.core.exceptions import HttpResponseError, ResourceExistsError, ResourceNotFoundError

    from savant.notion_oauth import BlobOAuthStore

    class Lease:
        def __init__(self, blob):
            self.blob = blob

        async def renew(self):
            pass

        async def release(self):
            self.blob.locked = False

    class Download:
        def __init__(self, data):
            self.data = data

        async def readall(self):
            return self.data

    class Blob:
        def __init__(self):
            self.data = None
            self.locked = False

        async def get_blob_properties(self):
            if self.data is None:
                raise ResourceNotFoundError("missing")
            return {}

        async def upload_blob(self, data, overwrite=False, lease=None):
            if self.data is not None and not overwrite:
                raise ResourceExistsError("exists")
            self.data = data

        async def acquire_lease(self, lease_duration):
            if self.locked:
                error = HttpResponseError("busy")
                error.status_code = 409
                raise error
            self.locked = True
            return Lease(self)

        async def download_blob(self, lease=None):
            # Lock-free snapshot reads are allowed; a leased read must hold the lease.
            assert lease is None or self.locked
            return Download(self.data)

    async def scenario():
        blob = Blob()
        key = Fernet.generate_key()

        def store():
            value = BlobOAuthStore.__new__(BlobOAuthStore)
            value.blob = blob
            value.cipher = Fernet(key)
            return value

        first, second = store(), store()
        refresh_calls = []
        failure = [True]

        async def handler(request):
            if failure[0]:
                return httpx.Response(503, json={"error": "private provider exception"})
            form = parse_qs(request.content.decode())
            refresh_calls.append(form["refresh_token"][0])
            await asyncio.sleep(0.05)
            return httpx.Response(200, json={"access_token": "new", "refresh_token": "rotated", "expires_in": 3600})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            a = NotionOAuth("https://app.example/oauth/notion/callback", first, client, lambda: 1000)
            b = NotionOAuth(a.callback_url, second, client, lambda: 1000)
            async with first.transaction() as data:
                data["client"] = {"client_id": "client", "token_endpoint": "https://mcp.notion.com/token"}
                data["tokens"] = {
                    a._user("alice"): {"access_token": "old", "refresh_token": "original", "expires_at": 900}
                }
            with pytest.raises(OAuthError, match="request failed"):
                await a.get_access_token("alice")
            assert not blob.locked
            failure[0] = False
            assert await asyncio.gather(a.get_access_token("alice"), b.get_access_token("alice")) == ["new", "new"]
            assert refresh_calls == ["original"]
            assert not blob.locked
            assert b"rotated" not in blob.data

    asyncio.run(scenario())


def test_callback_success_returns_only_confirmation(tmp_path):
    async def scenario():
        def handler(request):
            return httpx.Response(200, json={"access_token": "private-access", "refresh_token": "private-refresh"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as provider:
            store = SQLiteOAuthStore(str(tmp_path / "oauth.db"), Fernet.generate_key().decode())
            service = NotionOAuth("https://app.example/oauth/notion/callback", store, provider, lambda: 1000)
            async with store.transaction() as data:
                data["client"] = {"client_id": "client", "token_endpoint": "https://mcp.notion.com/token"}
                data["pending"] = {
                    "private-state": {
                        "user": service._user("alice"),
                        "expires_at": 1600,
                        "verifier": "private-verifier",
                    }
                }
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=create_callback_app(service)), base_url="https://app.example"
            ) as browser:
                response = await browser.get("/oauth/notion/callback?state=private-state&code=private-code")
            assert response.status_code == 200
            assert "Notion connected" in response.text
            assert "private-" not in response.text
            assert await service.get_access_token("alice") == "private-access"

    asyncio.run(scenario())


def test_valid_token_is_read_without_a_lease_and_remembered_briefly(tmp_path):
    key = Fernet.generate_key().decode()
    clock = [1000.0]

    class CountingStore(SQLiteOAuthStore):
        transactions = reads = 0

        def transaction(self):
            CountingStore.transactions += 1
            return super().transaction()

        async def read(self):
            CountingStore.reads += 1
            return await super().read()

    store = CountingStore(str(tmp_path / "oauth.db"), key)
    service = NotionOAuth("https://callback.example/oauth/notion/callback", store, clock=lambda: clock[0])

    async def scenario():
        async with store.transaction() as data:
            data["tokens"] = {
                service._user("alice"): {"access_token": "live", "refresh_token": None, "expires_at": clock[0] + 3600}
            }
        CountingStore.transactions = 0
        assert await service.get_access_token("alice") == "live"
        assert await service.get_access_token("alice") == "live"
        assert (CountingStore.reads, CountingStore.transactions) == (1, 0)
        clock[0] += NotionOAuth.FRESH_TOKEN_SECONDS + 1
        assert await service.get_access_token("alice") == "live"
        assert CountingStore.reads == 2
        assert await service.get_access_token("bob") is None
        await service.invalidate("alice")
        assert await service.get_access_token("alice") is None

    asyncio.run(scenario())
