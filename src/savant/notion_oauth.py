"""Direct Notion MCP OAuth: durable encrypted credentials, PKCE and rotation.

No network activity occurs at construction. Both callback and Hosted Agent must
use the same storage and encryption key. User IDs come from trusted request
identity, never model arguments.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import secrets
import sqlite3
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.fernet import Fernet

MCP_URL = "https://mcp.notion.com/mcp"


class OAuthError(RuntimeError):
    """Sanitized error safe to display; never includes provider payloads."""


class OAuthStore(Protocol):
    def transaction(self): ...

    # Optional: a lock-free snapshot for reads that change nothing (a valid access token).
    # async def read(self) -> dict: ...


class SQLiteOAuthStore:
    """Local development store. SQLite serializes processes, Fernet encrypts data."""

    def __init__(self, path: str, encryption_key: str):
        self.path = path
        self.cipher = Fernet(encryption_key.encode())
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(path, 0o600)

    async def read(self) -> dict:
        def load():
            connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            try:
                connection.execute("CREATE TABLE IF NOT EXISTS oauth (id INTEGER PRIMARY KEY, data BLOB NOT NULL)")
                row = connection.execute("SELECT data FROM oauth WHERE id=1").fetchone()
                return json.loads(self.cipher.decrypt(row[0])) if row else {}
            finally:
                connection.close()

        return await asyncio.to_thread(load)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[dict]:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        try:
            await asyncio.to_thread(connection.execute, "BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE IF NOT EXISTS oauth (id INTEGER PRIMARY KEY, data BLOB NOT NULL)")
            row = connection.execute("SELECT data FROM oauth WHERE id=1").fetchone()
            data = json.loads(self.cipher.decrypt(row[0])) if row else {}
            yield data
            encrypted = self.cipher.encrypt(json.dumps(data).encode())
            connection.execute("INSERT OR REPLACE INTO oauth VALUES (1, ?)", (encrypted,))
            connection.commit()
        finally:
            connection.close()


class BlobOAuthStore:
    """Shared cloud store, encrypted before upload and serialized with Blob leases.

    Container must already exist. Managed Identity requires Storage Blob Data
    Contributor. One document intentionally keeps the single-user prototype small.
    """

    def __init__(self, account_url: str, container: str, blob_name: str, encryption_key: str, credential):
        from azure.storage.blob.aio import BlobClient

        self.blob = BlobClient(account_url, container, blob_name, credential=credential)
        self.credential = credential
        self.cipher = Fernet(encryption_key.encode())

    async def close(self):
        await self.blob.close()
        await self.credential.close()

    async def read(self) -> dict:
        """One download, no lease and no write: a blob upload is atomic, so this is a consistent
        snapshot. Used only to return a still-valid token; anything that changes data leases."""
        from azure.core.exceptions import ResourceNotFoundError

        try:
            download = await self.blob.download_blob()
        except ResourceNotFoundError:
            return {}
        return json.loads(self.cipher.decrypt(await download.readall()))

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[dict]:
        from azure.core.exceptions import HttpResponseError, ResourceExistsError, ResourceNotFoundError

        try:
            await self.blob.get_blob_properties()
        except ResourceNotFoundError:
            try:
                await self.blob.upload_blob(self.cipher.encrypt(b"{}"), overwrite=False)
            except ResourceExistsError:
                pass
            except HttpResponseError as exc:
                if exc.status_code not in {409, 412}:
                    raise
                # Another instance can create and lease the blob between the
                # existence check and this conditional upload. Never overwrite it.
                await self.blob.get_blob_properties()
        deadline = time.monotonic() + 30
        while True:
            try:
                lease = await self.blob.acquire_lease(lease_duration=60)
                break
            except HttpResponseError as exc:
                if exc.status_code != 409 or time.monotonic() >= deadline:
                    raise OAuthError("Notion credential storage unavailable.") from None
                await asyncio.sleep(0.2)

        async def renew():
            while True:
                await asyncio.sleep(20)
                await lease.renew()

        renewal = asyncio.create_task(renew())
        try:
            download = await self.blob.download_blob(lease=lease)
            data = json.loads(self.cipher.decrypt(await download.readall()))
            yield data
            if renewal.done():
                renewal.result()
            await self.blob.upload_blob(self.cipher.encrypt(json.dumps(data).encode()), overwrite=True, lease=lease)
        finally:
            renewal.cancel()
            try:
                await renewal
            except (asyncio.CancelledError, Exception):
                pass
            await lease.release()


class NotionOAuth:
    def __init__(
        self, callback_url: str, store: OAuthStore, http_client: httpx.AsyncClient | None = None, clock=time.time
    ):
        url = urlsplit(callback_url)
        if url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"}):
            raise ValueError("OAuth callback requires HTTPS (HTTP loopback only for development).")
        if (
            url.query
            or url.fragment
            or url.username is not None
            or url.password is not None
            or not url.hostname
            or url.path != "/oauth/notion/callback"
        ):
            raise ValueError("Invalid OAuth callback URL.")
        self.callback_url, self.store, self.http_client, self.clock = callback_url, store, http_client, clock
        # A valid access token, remembered for a few seconds: one turn asks for it up to three
        # times. Never longer than FRESH_TOKEN_SECONDS, and dropped by invalidate().
        self._fresh: dict[str, tuple[float, str]] = {}

    @asynccontextmanager
    async def _http(self):
        if self.http_client is not None:
            yield self.http_client
        else:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                yield client

    @staticmethod
    def _endpoint(value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or url.hostname != "mcp.notion.com"
            or url.port not in {None, 443}
            or url.username is not None
            or url.password is not None
            or url.fragment
            or url.query
        ):
            raise OAuthError("Unexpected Notion OAuth endpoint.")
        return value

    async def _request(self, method, url, **kwargs):
        try:
            async with self._http() as client:
                response = await client.request(method, self._endpoint(url), **kwargs)
            body = response.json()
            if not response.is_success:
                if isinstance(body, dict) and body.get("error") == "invalid_grant":
                    raise OAuthError("invalid_grant")
                raise OAuthError("Notion OAuth request failed.")
            if not isinstance(body, dict):
                raise OAuthError("Invalid Notion OAuth response.")
            return body
        except (httpx.HTTPError, ValueError, TypeError):
            raise OAuthError("Notion OAuth service unavailable.") from None

    async def _client(self, data):
        existing = data.get("client")
        if existing:
            if existing["callback_url"] != self.callback_url:
                raise OAuthError("OAuth callback changed; use a separate credential store.")
            return existing
        metadata = await self._request("GET", "https://mcp.notion.com/.well-known/oauth-authorization-server")
        if "S256" not in metadata.get("code_challenge_methods_supported", []):
            raise OAuthError("Notion OAuth does not advertise required PKCE support.")
        try:
            endpoints = {
                name: self._endpoint(metadata[name])
                for name in ("authorization_endpoint", "token_endpoint", "registration_endpoint")
            }
        except (KeyError, TypeError):
            raise OAuthError("Invalid Notion OAuth metadata.") from None
        registration = await self._request(
            "POST",
            endpoints["registration_endpoint"],
            json={
                "client_name": "Savant Azurian 2",
                "redirect_uris": [self.callback_url],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": "default",
            },
        )
        if not isinstance(registration.get("client_id"), str) or not registration["client_id"]:
            raise OAuthError("Invalid Notion OAuth registration.")
        if registration.get("token_endpoint_auth_method", "none") != "none":
            raise OAuthError("Unsupported Notion OAuth client authentication method.")
        if "redirect_uris" in registration and registration["redirect_uris"] != [self.callback_url]:
            raise OAuthError("Unexpected Notion OAuth redirect URI.")
        data["client"] = dict(endpoints, client_id=registration["client_id"], callback_url=self.callback_url)
        return data["client"]

    @staticmethod
    def _user(user_id):
        if not isinstance(user_id, str) or not user_id.strip():
            raise OAuthError("Authenticated user identity is required to connect Notion.")
        return hashlib.sha256(user_id.encode()).hexdigest()

    async def begin(self, user_id: str) -> str:
        user = self._user(user_id)
        async with self.store.transaction() as data:
            client = await self._client(data)
            pending = data.setdefault("pending", {})
            now = self.clock()
            for state in list(pending):
                if pending[state]["expires_at"] <= now:
                    del pending[state]
            for flow in pending.values():
                if flow["user"] == user:
                    return flow["url"]
            state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            url = (
                client["authorization_endpoint"]
                + "?"
                + urlencode(
                    {
                        "response_type": "code",
                        "client_id": client["client_id"],
                        "redirect_uri": self.callback_url,
                        "state": state,
                        "code_challenge": challenge,
                        "code_challenge_method": "S256",
                        "resource": MCP_URL,
                        "scope": "default",
                        "prompt": "consent",
                    }
                )
            )
            pending[state] = {"user": user, "verifier": verifier, "expires_at": now + 600, "url": url}
            return url

    async def finish(self, state: str, code: str | None = None, error: str | None = None) -> None:
        # Consume durably before external exchange: callbacks cannot replay even on errors.
        async with self.store.transaction() as data:
            flow = data.setdefault("pending", {}).pop(state, None)
            client = data.get("client")
        if not flow or flow["expires_at"] <= self.clock():
            raise OAuthError("OAuth link expired or already used. Request a new link in the chat.")
        if error:
            raise OAuthError("Notion authorization was declined. Request a new link to retry.")
        if not code or not client:
            raise OAuthError("Missing OAuth authorization code.")
        async with self.store.transaction() as data:
            tokens = await self._request(
                "POST",
                client["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "client_id": client["client_id"],
                    "redirect_uri": self.callback_url,
                    "code": code,
                    "code_verifier": flow["verifier"],
                    "resource": MCP_URL,
                },
            )
            data.setdefault("tokens", {})[flow["user"]] = self._tokens(tokens)

    def _tokens(self, tokens, previous=None):
        if not isinstance(tokens.get("access_token"), str) or not tokens["access_token"]:
            raise OAuthError("Missing Notion access token.")
        if str(tokens.get("token_type", "Bearer")).lower() != "bearer":
            raise OAuthError("Unsupported Notion token type.")
        try:
            lifetime = float(tokens.get("expires_in", 3600))
        except (ValueError, TypeError):
            raise OAuthError("Invalid Notion token lifetime.") from None
        if not math.isfinite(lifetime) or lifetime <= 0:
            raise OAuthError("Invalid Notion token lifetime.")
        if tokens.get("refresh_token") is not None and (
            not isinstance(tokens["refresh_token"], str) or not tokens["refresh_token"]
        ):
            raise OAuthError("Invalid Notion refresh token.")
        return {
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token") or (previous or {}).get("refresh_token"),
            "expires_at": self.clock() + lifetime,
        }

    FRESH_TOKEN_SECONDS = 30.0

    async def get_access_token(self, user_id: str) -> str | None:
        user = self._user(user_id)
        remembered = self._fresh.get(user)
        if remembered and remembered[0] > self.clock():
            return remembered[1]
        read = getattr(self.store, "read", None)
        if read is not None:
            # Fast path: a lock-free snapshot is enough when the token is still valid or absent.
            # Only a refresh (which writes) takes the leased transaction below.
            token = (await read()).get("tokens", {}).get(user)
            if not token:
                return None
            if token["expires_at"] > self.clock() + 60:
                self._remember(user, token)
                return token["access_token"]
        async with self.store.transaction() as data:
            token = data.setdefault("tokens", {}).get(user)
            if not token:
                return None
            if token["expires_at"] > self.clock() + 60:
                return token["access_token"]
            if not token.get("refresh_token"):
                del data["tokens"][user]
                return None
            client = data["client"]
            try:
                refreshed = await self._request(
                    "POST",
                    client["token_endpoint"],
                    data={
                        "grant_type": "refresh_token",
                        "client_id": client["client_id"],
                        "refresh_token": token["refresh_token"],
                        "resource": MCP_URL,
                    },
                )
            except OAuthError as exc:
                if str(exc) != "invalid_grant":
                    raise
                del data["tokens"][user]
                return None
            data["tokens"][user] = self._tokens(refreshed, token)
            self._remember(user, data["tokens"][user])
            return data["tokens"][user]["access_token"]

    def _remember(self, user: str, token: dict) -> None:
        lifetime = min(self.FRESH_TOKEN_SECONDS, token["expires_at"] - self.clock() - 60)
        if lifetime > 0:
            self._fresh[user] = (self.clock() + lifetime, token["access_token"])

    async def invalidate(self, user_id: str) -> None:
        """Remove a revoked grant after MCP rejects it; do not retry writes."""
        user = self._user(user_id)
        self._fresh.pop(user, None)
        async with self.store.transaction() as data:
            data.setdefault("tokens", {}).pop(user, None)
