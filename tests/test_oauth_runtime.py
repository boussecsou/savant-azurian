import asyncio
import sys
from types import SimpleNamespace

from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceNotFoundError, ServiceRequestError
from azure.identity import CredentialUnavailableError
from cryptography.fernet import Fernet
import httpx
import pytest

from savant.oauth_runtime import build_oauth_service
from savant.oauth_callback import create_callback_app


@pytest.fixture(autouse=True)
def isolated_oauth_environment(monkeypatch):
    for name in ("NOTION_OAUTH_ENCRYPTION_KEY", "NOTION_OAUTH_KEY_VAULT_URL",
                 "NOTION_OAUTH_KEY_VAULT_SECRET_NAME", "NOTION_OAUTH_MANAGED_IDENTITY_CLIENT_ID"):
        monkeypatch.delenv(name, raising=False)


def test_agent_reads_key_vault_key_and_shares_encrypted_store_with_bff(monkeypatch, tmp_path):
    key = Fernet.generate_key().decode()
    monkeypatch.delenv("NOTION_OAUTH_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("NOTION_OAUTH_KEY_VAULT_URL", "https://test.vault.azure.net")
    monkeypatch.setenv("NOTION_OAUTH_KEY_VAULT_SECRET_NAME", "notion-oauth-encryption-key")
    closed = []

    class Credential:
        def close(self):
            closed.append("credential")

    class Vault:
        def __init__(self, vault_url, credential, **kwargs):
            assert vault_url == "https://test.vault.azure.net"

        def get_secret(self, name):
            assert name == "notion-oauth-encryption-key"
            return SimpleNamespace(value=key)

        def close(self):
            closed.append("client")

    monkeypatch.setattr("azure.identity.DefaultAzureCredential", Credential)
    monkeypatch.setattr("azure.keyvault.secrets.SecretClient", Vault)
    callback = "http://localhost:8090/oauth/notion/callback"
    store_url = "sqlite://" + str(tmp_path / "oauth.db")
    agent = build_oauth_service(callback, store_url, use_key_vault=True)
    assert closed == ["client", "credential"]

    monkeypatch.setenv("NOTION_OAUTH_ENCRYPTION_KEY", key)
    bff = build_oauth_service(callback, store_url)

    async def scenario():
        async with bff.store.transaction() as data:
            data["test-grant"] = "synthetic-token"
        async with agent.store.transaction() as data:
            assert data["test-grant"] == "synthetic-token"

    asyncio.run(scenario())
    assert b"synthetic-token" not in (tmp_path / "oauth.db").read_bytes()


@pytest.mark.parametrize(("failure", "message"), [
    (ResourceNotFoundError("private-sdk-payload"), "not found"),
    (HttpResponseError("private-sdk-payload", response=SimpleNamespace(status_code=403, reason="Forbidden", headers={})), "access was denied"),
    (ClientAuthenticationError("private-sdk-payload"), "authentication failed"),
    (CredentialUnavailableError("private-sdk-payload"), "authentication failed"),
    (ServiceRequestError("private-sdk-payload"), "could not be retrieved"),
])
def test_key_vault_failures_are_sanitized_without_env_fallback(monkeypatch, tmp_path, caplog, failure, message):
    monkeypatch.setenv("NOTION_OAUTH_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("NOTION_OAUTH_KEY_VAULT_URL", "https://test.vault.azure.net")
    monkeypatch.setenv("NOTION_OAUTH_KEY_VAULT_SECRET_NAME", "notion-oauth-encryption-key")
    closed = []

    class Credential:
        def close(self):
            closed.append("credential")

    class Vault:
        def __init__(self, **kwargs):
            pass

        def get_secret(self, name):
            raise failure

        def close(self):
            closed.append("client")

    monkeypatch.setattr("azure.identity.DefaultAzureCredential", Credential)
    monkeypatch.setattr("azure.keyvault.secrets.SecretClient", Vault)
    with pytest.raises(RuntimeError, match=message) as caught:
        build_oauth_service("http://localhost:8090/oauth/notion/callback",
                            "sqlite://" + str(tmp_path / "oauth.db"), use_key_vault=True)
    assert "private-sdk-payload" not in str(caught.value) + caplog.text
    assert caught.value.__suppress_context__
    assert closed == ["client", "credential"]
    assert not (tmp_path / "oauth.db").exists()


@pytest.mark.parametrize("value", [None, "", "invalid-fernet-key", "non-ascii-é"])
def test_invalid_or_empty_key_vault_secret_fails_before_creating_store(monkeypatch, tmp_path, value):
    monkeypatch.setenv("NOTION_OAUTH_KEY_VAULT_URL", "https://test.vault.azure.net")
    monkeypatch.setenv("NOTION_OAUTH_KEY_VAULT_SECRET_NAME", "notion-oauth-encryption-key")

    class Credential:
        def close(self):
            pass

    class Vault:
        def __init__(self, **kwargs):
            pass

        def get_secret(self, name):
            return SimpleNamespace(value=value)

        def close(self):
            pass

    monkeypatch.setattr("azure.identity.DefaultAzureCredential", Credential)
    monkeypatch.setattr("azure.keyvault.secrets.SecretClient", Vault)
    with pytest.raises(RuntimeError, match="empty|valid Fernet"):
        build_oauth_service("http://localhost:8090/oauth/notion/callback",
                            "sqlite://" + str(tmp_path / "oauth.db"), use_key_vault=True)
    assert not (tmp_path / "oauth.db").exists()


@pytest.mark.parametrize(("vault_url", "secret_name"), [
    ("", "notion-oauth-encryption-key"),
    ("https://test.vault.azure.net", ""),
    ("http://test.vault.azure.net", "key"),
    ("https://attacker.example", "key"),
    ("https://test.vault.azure.net/secrets/key", "key"),
    ("https://user:password@test.vault.azure.net", "key"),
    ("https://test.vault.azure.net?credential=private", "key"),
    ("https://test.vault.azure.net", "key/version"),
])
def test_invalid_vault_configuration_makes_no_sdk_calls(monkeypatch, tmp_path, vault_url, secret_name):
    monkeypatch.setenv("NOTION_OAUTH_KEY_VAULT_URL", vault_url)
    monkeypatch.setenv("NOTION_OAUTH_KEY_VAULT_SECRET_NAME", secret_name)
    monkeypatch.setitem(sys.modules, "azure.keyvault.secrets", None)
    with pytest.raises(RuntimeError, match="NOTION_OAUTH_KEY_VAULT"):
        build_oauth_service("http://localhost:8090/oauth/notion/callback",
                            "sqlite://" + str(tmp_path / "oauth.db"), use_key_vault=True)


def test_bff_native_injection_needs_no_key_vault_sdk_and_is_ready(monkeypatch, tmp_path):
    monkeypatch.setenv("NOTION_OAUTH_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("NOTION_OAUTH_KEY_VAULT_URL", "https://test.vault.azure.net")
    monkeypatch.setenv("NOTION_OAUTH_KEY_VAULT_SECRET_NAME", "notion-oauth-encryption-key")
    monkeypatch.setitem(sys.modules, "azure.keyvault.secrets", None)
    service = build_oauth_service("http://localhost:8090/oauth/notion/callback",
                                 "sqlite://" + str(tmp_path / "oauth.db"))

    async def scenario():
        app = create_callback_app(service)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bff") as client:
                response = await client.get("/readiness")
                assert response.status_code == 200
                assert response.json() == {"status": "ready"}

    asyncio.run(scenario())


@pytest.mark.parametrize("key", [None, "", "invalid-key", "non-ascii-é"])
def test_native_injection_requires_valid_fernet_key(monkeypatch, tmp_path, key):
    monkeypatch.delenv("NOTION_OAUTH_ENCRYPTION_KEY", raising=False)
    if key is not None:
        monkeypatch.setenv("NOTION_OAUTH_ENCRYPTION_KEY", key)
    with pytest.raises(RuntimeError, match="required|valid Fernet"):
        build_oauth_service("http://localhost:8090/oauth/notion/callback",
                            "sqlite://" + str(tmp_path / "oauth.db"))
    assert not (tmp_path / "oauth.db").exists()


def test_specific_identity_is_used_for_both_key_vault_and_blob(monkeypatch):
    key = Fernet.generate_key().decode()
    client_id = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setenv("NOTION_OAUTH_MANAGED_IDENTITY_CLIENT_ID", client_id)
    monkeypatch.setenv("NOTION_OAUTH_KEY_VAULT_URL", "https://test.vault.azure.net")
    monkeypatch.setenv("NOTION_OAUTH_KEY_VAULT_SECRET_NAME", "notion-oauth-encryption-key")
    selected = []

    class Credential:
        def __init__(self, **kwargs):
            selected.append(kwargs["client_id"])

        def close(self):
            pass

    class AsyncCredential(Credential):
        async def get_token(self, *args, **kwargs):
            raise AssertionError("Blob storage must not authenticate at construction")

        async def close(self):
            pass

    class Vault:
        def __init__(self, **kwargs):
            pass

        def get_secret(self, name):
            return SimpleNamespace(value=key)

        def close(self):
            pass

    def no_fallback(*args, **kwargs):
        raise AssertionError("An explicitly selected identity must not use a fallback chain")

    monkeypatch.setattr("azure.identity.ManagedIdentityCredential", Credential)
    monkeypatch.setattr("azure.identity.aio.ManagedIdentityCredential", AsyncCredential)
    monkeypatch.setattr("azure.identity.DefaultAzureCredential", no_fallback)
    monkeypatch.setattr("azure.identity.aio.DefaultAzureCredential", no_fallback)
    monkeypatch.setattr("azure.keyvault.secrets.SecretClient", Vault)
    service = build_oauth_service("https://bff.example/oauth/notion/callback",
                                 "https://test.blob.core.windows.net/notion-oauth/grants.bin",
                                 use_key_vault=True)
    assert selected == [client_id, client_id]
    asyncio.run(service.store.close())


def test_callback_entrypoint_binds_public_interface_and_disables_access_logs(monkeypatch, tmp_path):
    from savant.oauth_callback import main
    from savant.bff_logging import LOGGING_CONFIG

    monkeypatch.setattr("savant.bff_logging.configure_bff_logging", lambda: None)
    monkeypatch.setenv("NOTION_OAUTH_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("NOTION_OAUTH_CALLBACK_URL", "http://localhost:8090/oauth/notion/callback")
    monkeypatch.setenv("NOTION_OAUTH_STORE_URL", "sqlite://" + str(tmp_path / "oauth.db"))
    monkeypatch.delenv("OAUTH_CALLBACK_PORT", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda **kwargs: None)
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(kwargs))
    main()
    assert captured == {"host": "0.0.0.0", "port": 8090, "access_log": False, "log_config": LOGGING_CONFIG}


def test_invalid_identity_selector_fails_without_credential_fallback(monkeypatch):
    monkeypatch.setenv("NOTION_OAUTH_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("NOTION_OAUTH_MANAGED_IDENTITY_CLIENT_ID", "private-invalid-selector")
    with pytest.raises(RuntimeError, match="client UUID") as caught:
        build_oauth_service("https://bff.example/oauth/notion/callback",
                            "https://test.blob.core.windows.net/notion-oauth/grants.bin")
    assert "private-invalid-selector" not in str(caught.value)
