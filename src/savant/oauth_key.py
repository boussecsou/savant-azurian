"""Resolve the shared Fernet key without exposing secret or SDK error payloads."""

import os
import re
from contextlib import ExitStack
from urllib.parse import urlsplit
from uuid import UUID

from cryptography.fernet import Fernet


def oauth_azure_credential(*, asynchronous: bool = False):
    """Use a specific MI when configured; developer credentials otherwise."""
    if asynchronous:
        from azure.identity.aio import DefaultAzureCredential, ManagedIdentityCredential
    else:
        from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

    client_id = os.environ.get("NOTION_OAUTH_MANAGED_IDENTITY_CLIENT_ID", "").strip()
    if client_id:
        try:
            UUID(client_id)
        except ValueError:
            raise RuntimeError("NOTION_OAUTH_MANAGED_IDENTITY_CLIENT_ID must be a client UUID.") from None
        return ManagedIdentityCredential(client_id=client_id)
    return DefaultAzureCredential()


def load_fernet_key(*, use_key_vault: bool = False) -> str:
    """BFF uses native secret injection; only the agent opts into SDK access."""
    vault_url = os.environ.get("NOTION_OAUTH_KEY_VAULT_URL", "").strip()
    secret_name = os.environ.get("NOTION_OAUTH_KEY_VAULT_SECRET_NAME", "").strip()
    if use_key_vault and (vault_url or secret_name):
        # A configured vault is authoritative: never fall back to an env key.
        key = _read_key_vault(vault_url, secret_name)
    else:
        key = os.environ.get("NOTION_OAUTH_ENCRYPTION_KEY", "").strip()
        if not key:
            raise RuntimeError("NOTION_OAUTH_ENCRYPTION_KEY is required for encrypted OAuth storage.")
    try:
        Fernet(key.encode("ascii"))
    except (ValueError, UnicodeError, AttributeError):
        raise RuntimeError("OAuth encryption key is not a valid Fernet key.") from None
    return key


def _read_key_vault(vault_url: str, secret_name: str) -> str:
    parsed = urlsplit(vault_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith((".vault.azure.net", ".vault.usgovcloudapi.net", ".vault.azure.cn"))
        or parsed.netloc != parsed.hostname
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("NOTION_OAUTH_KEY_VAULT_URL must be an HTTPS Azure Key Vault URL.")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,127}", secret_name):
        raise RuntimeError("NOTION_OAUTH_KEY_VAULT_SECRET_NAME must name an existing Key Vault secret.")

    # Lazy imports keep the callback independent of the Key Vault SDK.
    from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceNotFoundError
    from azure.identity import CredentialUnavailableError
    from azure.keyvault.secrets import SecretClient

    try:
        with ExitStack() as resources:
            credential = oauth_azure_credential()
            resources.callback(credential.close)
            client = SecretClient(vault_url=vault_url, credential=credential, logging_enable=False)
            resources.callback(client.close)
            key = client.get_secret(secret_name).value
    except (CredentialUnavailableError, ClientAuthenticationError):
        raise RuntimeError("OAuth Key Vault authentication failed.") from None
    except ResourceNotFoundError:
        raise RuntimeError("OAuth encryption secret was not found in Key Vault.") from None
    except HttpResponseError as exc:
        if exc.status_code == 403:
            raise RuntimeError("OAuth Key Vault access was denied.") from None
        raise RuntimeError("OAuth Key Vault secret could not be retrieved.") from None
    except Exception:
        raise RuntimeError("OAuth Key Vault secret could not be retrieved.") from None
    if not key:
        raise RuntimeError("OAuth encryption secret is empty in Key Vault.")
    return key
