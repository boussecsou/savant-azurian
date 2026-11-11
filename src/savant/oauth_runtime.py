"""Construct OAuth storage; agent startup can optionally read its key from Azure."""

from urllib.parse import urlsplit

from .notion_oauth import BlobOAuthStore, NotionOAuth, SQLiteOAuthStore
from .oauth_key import load_fernet_key, oauth_azure_credential


def build_oauth_service(callback_url: str, store_url: str, *, use_key_vault: bool = False):
    parsed = urlsplit(store_url)
    if parsed.query or parsed.fragment or parsed.username is not None or parsed.password is not None:
        raise RuntimeError("OAuth storage URLs must not contain credentials, queries or fragments.")
    if parsed.scheme == "sqlite" and not parsed.netloc and parsed.path.startswith("/"):
        if urlsplit(callback_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise RuntimeError("SQLite OAuth storage is only supported for local callbacks.")
        store = SQLiteOAuthStore(parsed.path, load_fernet_key(use_key_vault=use_key_vault))
    elif parsed.scheme == "https" and parsed.hostname and parsed.hostname.endswith(".blob.core.windows.net"):
        path = parsed.path.lstrip("/").split("/", 1)
        if len(path) != 2 or not all(path) or parsed.port not in {None, 443}:
            raise RuntimeError("OAuth Blob URL must include an existing container and blob name.")
        key = load_fernet_key(use_key_vault=use_key_vault)
        store = BlobOAuthStore(
            f"https://{parsed.hostname}", path[0], path[1], key, oauth_azure_credential(asynchronous=True)
        )
    else:
        raise RuntimeError("NOTION_OAUTH_STORE_URL must be sqlite:///absolute/path locally or an HTTPS Azure Blob URL.")
    return NotionOAuth(callback_url, store)
