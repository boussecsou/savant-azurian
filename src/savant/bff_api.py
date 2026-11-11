"""Owner-only PWA routes of the BFF: Notion consent, status and chat relay.

Container Apps built-in authentication (Easy Auth) validates the caller's Microsoft
Entra token before the request reaches this code and injects X-MS-CLIENT-PRINCIPAL-*
headers (external requests cannot set them). The BFF only accepts the one Entra
object ID it is configured with. The owner key used for Notion grants is a separate,
fixed server-side value; nothing sent by the client can choose it.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from savant.bff_workspace import create_workspace_router
from savant.correlation import correlation_id
from savant.notion_oauth import NotionOAuth, OAuthError
from savant.workspace import WorkspaceError, WorkspaceService

logger = logging.getLogger("savant.bff")

PRINCIPAL_ID_HEADER = "x-ms-client-principal-id"
PRINCIPAL_IDP_HEADER = "x-ms-client-principal-idp"
ENTRA_IDP = "aad"
AGENT_TOKEN_SCOPE = "https://ai.azure.com/.default"
# The relay must cover the agent's Notion tool calls (measured: 66 s for one read) while staying
# below the Container Apps ingress request timeout (documented default: 240 s).
AGENT_TIMEOUT_SECONDS = 120
# Streaming: the read timeout bounds the silence between two events (a cold agent can be silent
# for a while), the deadline bounds the whole answer, both below the ingress limit.
STREAM_DEADLINE_SECONDS = 220
# Same text as savant.health.RUNTIME_SMOKE_PROMPT (tests keep them equal): the BFF image does not
# ship that module. The agent answers it from the tool-free path, with no Notion and no OAuth.
WARMUP_PROMPT = "Savant runtime model probe. Reply with exactly SA2_RUNTIME_MODEL_OK. Do not call any tools."
WARMUP_EXPECTED = "SA2_RUNTIME_MODEL_OK"
_CONVERSATION_ID = r"^[A-Za-z0-9_.:-]{1,256}$"
_SAFE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,256}")
_TOOL_NAME = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
AGENT_API_VERSION = "v1"
# Voice: the browser talks to Azure Speech directly with a short-lived Speech token minted here with
# the BFF's managed identity (Entra, no key). Speech tokens last 10 minutes; reuse one for 8.
SPEECH_SCOPE = "https://cognitiveservices.azure.com/.default"
SPEECH_TOKEN_REUSE_SECONDS = 480
SPEECH_TOKEN_LIFETIME_SECONDS = 600
_SPEECH_REGION = re.compile(r"[a-z0-9]{2,40}")
_OBJECT_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


@dataclass(frozen=True)
class ApiSettings:
    owner_id: str
    agent_responses_url: str
    pwa_origin: str = ""
    # Entra object ID of the only caller allowed in (lowercase GUID); not the Notion key above.
    owner_object_id: str = field(kw_only=True)
    # Optional voice: the AI Services custom-domain endpoint and its region, both or neither.
    speech_endpoint: str = field(default="", kw_only=True)
    speech_region: str = field(default="", kw_only=True)
    # Optional workspace storage (Cosmos DB): the endpoint enables projects and sessions.
    cosmos_endpoint: str = field(default="", kw_only=True)
    cosmos_database: str = field(default="sa2", kw_only=True)
    # Optional project documents (Blob + Azure AI Search): both the account and the search endpoint.
    documents_account_url: str = field(default="", kw_only=True)
    documents_container: str = field(default="documents", kw_only=True)
    search_endpoint: str = field(default="", kw_only=True)
    search_index: str = field(default="sa2-docs", kw_only=True)
    search_indexer: str = field(default="sa2-docs-indexer", kw_only=True)

    @classmethod
    def from_env(cls) -> ApiSettings | None:
        """Return None unless the PWA API is configured; the callback keeps working alone."""
        owner = os.environ.get("NOTION_OWNER_ID", "").strip()
        url = os.environ.get("AGENT_RESPONSES_URL", "").strip()
        origin = os.environ.get("PWA_ORIGIN", "").strip()
        object_id = os.environ.get("BFF_OWNER_OBJECT_ID", "").strip().lower()
        # The deployed BFF may already hold NOTION_OWNER_ID: only the agent URL enables the API.
        if not url:
            return None
        if not owner:
            raise RuntimeError("NOTION_OWNER_ID is required when AGENT_RESPONSES_URL is set.")
        if not _OBJECT_ID.fullmatch(object_id):
            raise RuntimeError(
                "BFF_OWNER_OBJECT_ID must be the owner's Microsoft Entra object ID (a GUID) "
                "when AGENT_RESPONSES_URL is set."
            )
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or not parsed.hostname.endswith(".azure.com")
        ):
            raise RuntimeError("AGENT_RESPONSES_URL must be an HTTPS Azure URL.")
        url = _with_api_version(parsed)
        speech_endpoint = os.environ.get("SPEECH_ENDPOINT", "").strip().rstrip("/")
        speech_region = os.environ.get("SPEECH_REGION", "").strip().lower()
        if bool(speech_endpoint) != bool(speech_region):
            raise RuntimeError("SPEECH_ENDPOINT and SPEECH_REGION must be set together.")
        if speech_endpoint:
            speech = urlsplit(speech_endpoint)
            if (
                speech.scheme != "https"
                or not speech.hostname
                or not speech.hostname.endswith(".cognitiveservices.azure.com")
                or speech.path
                or speech.query
                or speech.fragment
                or speech.username
            ):
                raise RuntimeError(
                    "SPEECH_ENDPOINT must be an HTTPS *.cognitiveservices.azure.com custom-domain origin."
                )
            if not _SPEECH_REGION.fullmatch(speech_region):
                raise RuntimeError("SPEECH_REGION must be an Azure region name such as italynorth.")
        cosmos_endpoint = os.environ.get("COSMOS_ENDPOINT", "").strip().rstrip("/")
        cosmos_database = os.environ.get("COSMOS_DATABASE", "sa2").strip()
        if cosmos_endpoint:
            cosmos = urlsplit(cosmos_endpoint)
            if (
                cosmos.scheme != "https"
                or not cosmos.hostname
                or not cosmos.hostname.endswith(".documents.azure.com")
                or cosmos.path not in ("", "/")
                or cosmos.query
                or cosmos.fragment
                or cosmos.username
            ):
                raise RuntimeError("COSMOS_ENDPOINT must be an HTTPS *.documents.azure.com account origin.")
            if not _SAFE_ID.fullmatch(cosmos_database):
                raise RuntimeError("COSMOS_DATABASE must be a plain database name such as sa2.")
        if origin:
            parts = urlsplit(origin)
            local = parts.hostname in {"localhost", "127.0.0.1"}
            if (
                parts.scheme not in ({"https", "http"} if local else {"https"})
                or not parts.hostname
                or parts.path
                or parts.query
                or parts.fragment
                or parts.username
            ):
                raise RuntimeError("PWA_ORIGIN must be an origin (HTTPS, or HTTP on localhost).")
        return cls(
            owner,
            url,
            origin,
            owner_object_id=object_id,
            speech_endpoint=speech_endpoint,
            speech_region=speech_region,
            cosmos_endpoint=cosmos_endpoint,
            cosmos_database=cosmos_database,
            **_documents_settings(bool(cosmos_endpoint)),
        )


_NAME = re.compile(r"[a-z0-9][a-z0-9-]{1,62}")


def _documents_settings(has_workspace: bool) -> dict:
    """Project documents: the Blob account and the search endpoint together, or neither."""
    # DOCUMENTS_ACCOUNT_URL turns the feature on. SEARCH_ENDPOINT alone (the agent's variable) is ignored.
    account = os.environ.get("DOCUMENTS_ACCOUNT_URL", "").strip().rstrip("/")
    search = os.environ.get("SEARCH_ENDPOINT", "").strip().rstrip("/")
    if not account:
        return {}
    if not search:
        raise RuntimeError("DOCUMENTS_ACCOUNT_URL needs SEARCH_ENDPOINT (the Azure AI Search service).")
    if not has_workspace:
        raise RuntimeError("Project documents need the workspace (COSMOS_ENDPOINT).")
    if not re.fullmatch(r"https://[a-z0-9]{3,24}\.blob\.core\.windows\.net", account):
        raise RuntimeError("DOCUMENTS_ACCOUNT_URL must be https://<account>.blob.core.windows.net.")
    if not re.fullmatch(r"https://[a-z0-9][a-z0-9-]{0,59}\.search\.windows\.net", search):
        raise RuntimeError("SEARCH_ENDPOINT must be https://<service>.search.windows.net.")
    names = {
        "documents_container": os.environ.get("DOCUMENTS_CONTAINER", "documents").strip(),
        "search_index": os.environ.get("SEARCH_INDEX", "sa2-docs").strip(),
        "search_indexer": os.environ.get("SEARCH_INDEXER", "sa2-docs-indexer").strip(),
    }
    if not all(_NAME.fullmatch(value) for value in names.values()):
        raise RuntimeError("DOCUMENTS_CONTAINER, SEARCH_INDEX and SEARCH_INDEXER must be plain names.")
    return {"documents_account_url": account, "search_endpoint": search, **names}


def _with_api_version(parsed) -> str:
    """The Foundry agent endpoint answers 400 without api-version: add it unless the URL has one."""
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if not any(name.lower() == "api-version" for name, _ in query):
        query.append(("api-version", AGENT_API_VERSION))
    return urlunsplit(parsed._replace(query=urlencode(query)))


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = Field(default=None, pattern=_CONVERSATION_ID)
    # "voice" when the PWA's voice mode sends the transcript: the agent then answers for the ear.
    mode: Literal["text", "voice"] = "text"
    # A stored session: the BFF then knows its project and where its thread continues, and keeps the turn.
    session_id: str | None = Field(default=None, pattern=_CONVERSATION_ID)


def _agent_payload(body: ChatRequest, *, stream: bool, session: dict | None = None) -> dict:
    payload = {"input": body.message, "stream": stream}
    # The PWA's own thread id wins; a session continues from the last answer it stored.
    previous = body.conversation_id or (session or {}).get("conversationId")
    if previous:
        payload["previous_response_id"] = previous
    metadata = {}
    if body.mode == "voice":
        metadata["channel"] = "voice"
    if session:
        # Set here, from the stored session: the model never chooses the project (SDD-005 D6).
        metadata["project_id"] = session["projectId"]
    if metadata:
        payload["metadata"] = metadata
    return payload


def _owner_check(settings: ApiSettings):
    def require_owner(request: Request) -> None:
        """Fail closed unless Easy Auth vouches for the configured Entra object ID."""
        caller = request.headers.get(PRINCIPAL_ID_HEADER, "").strip().lower()
        if not caller:
            raise HTTPException(401)
        idp = request.headers.get(PRINCIPAL_IDP_HEADER, "").strip().lower()
        if idp != ENTRA_IDP or not hmac.compare_digest(caller.encode(), settings.owner_object_id.encode()):
            raise HTTPException(403)

    return require_owner


def _reply_text(body: dict) -> str:
    return "".join(
        part.get("text", "")
        for item in body.get("output", [])
        if isinstance(item, dict) and item.get("type") == "message"
        for part in item.get("content", [])
        if isinstance(part, dict) and part.get("type") == "output_text"
    )


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, separators=(',', ':'))}\n\n"


def _safe(pattern, value, default=None):
    return value if isinstance(value, str) and pattern.fullmatch(value) else default


def _asks_for_sign_in(output) -> bool:
    return isinstance(output, str) and "consent.azure-apihub.net/login" in output


def _dispatched_name(arguments) -> str | None:
    try:
        parsed = json.loads(arguments) if isinstance(arguments, str) else None
    except ValueError:
        return None
    return _safe(_TOOL_NAME, parsed.get("name")) if isinstance(parsed, dict) else None


def _translate(event) -> list[dict]:
    """Map one agent stream event to the PWA's small vocabulary.

    Only assistant text, tool names and the next conversation id pass through. Reasoning,
    tool arguments and tool results (the owner's Notion data) are dropped here.
    """
    kind = event.get("type") if isinstance(event, dict) else None
    if kind == "response.output_text.delta":
        text = event.get("delta")
        return [{"type": "delta", "text": text}] if isinstance(text, str) and text else []
    if kind in ("response.output_item.added", "response.output_item.done"):
        item = event.get("item")
        if not isinstance(item, dict):
            return []
        call_id = _safe(_SAFE_ID, item.get("call_id")) or _safe(_SAFE_ID, item.get("id"))
        if call_id is None:
            return []
        if item.get("type") == "function_call" and kind.endswith("added"):
            return [
                {
                    "type": "tool",
                    "id": call_id,
                    "name": _safe(_TOOL_NAME, item.get("name"), "tool"),
                    "status": "running",
                }
            ]
        if item.get("type") == "function_call" and kind.endswith("done") and item.get("name") == "call_tool":
            # The toolbox dispatcher hides the real tool in its arguments: relay only that name,
            # once the arguments are complete, so the PWA can label the step. Nothing else leaks.
            inner = _dispatched_name(item.get("arguments"))
            return [{"type": "tool", "id": call_id, "name": inner, "status": "running"}] if inner else []
        if item.get("type") == "function_call_output":
            done = {"type": "tool", "id": call_id, "status": "done"}
            if _asks_for_sign_in(item.get("output")):
                # The toolbox answers a not-yet-authorised connector with a sign-in link instead of data.
                # Only the fact reaches the PWA (so it can show "sign-in needed"), never the link.
                done["consent"] = True
            return [done]
        return []
    if kind in ("response.completed", "response.incomplete"):
        response = event.get("response")
        conversation = _safe(_SAFE_ID, response.get("id")) if isinstance(response, dict) else None
        return [{"type": "done", "conversation_id": conversation}] if conversation else []
    if kind in ("response.failed", "error"):
        return [{"type": "error", "kind": "upstream"}]
    return []


DOCUMENT_SEARCH_TOOL = "search_documents"
_DOCUMENT_ID = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
_SOURCE_TITLE_MAX = 120


def _sources(output) -> list[dict]:
    """The documents a `search_documents` result cites: id and file name only, never the passages.

    The agent wraps the result as outside data (<untrusted_data ...>{json}</untrusted_data>): read the
    JSON between the first "{" and the last "}", keep well-formed ids, and drop everything else."""
    text = output if isinstance(output, str) else ""
    start, end = text.find("{"), text.rfind("}")
    try:
        results = json.loads(text[start : end + 1]).get("results") if start != -1 and end > start else None
    except (ValueError, AttributeError):
        return []
    sources, seen = [], set()
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict):
            continue
        document_id, title = item.get("document_id"), item.get("title")
        if (
            isinstance(document_id, str)
            and _DOCUMENT_ID.fullmatch(document_id)
            and document_id not in seen
            and isinstance(title, str)
            and title.strip()
        ):
            seen.add(document_id)
            clean = "".join(c for c in title if c.isprintable())[:_SOURCE_TITLE_MAX]
            sources.append({"documentId": document_id, "title": clean})
    return sources


async def _relay_events(lines, on_done=None):
    """Turn the agent's SSE lines into PWA events, always ending with `done` or `error`.

    `on_done(answer_text, conversation_id)` runs once the answer is complete; its failure never
    reaches the owner, who already has the answer.
    """
    started = time.monotonic()
    finished = False
    answer: list[str] = []
    # call id -> tool name, so the result of a document search can be recognised (it carries no name).
    tool_names: dict[str, str] = {}
    cited_calls: set[str] = set()
    try:
        async for line in lines:
            if time.monotonic() - started > STREAM_DEADLINE_SECONDS:
                logger.warning("chat_stream_failed", extra={"error_type": "DeadlineExceeded"})
                yield _sse({"type": "error", "kind": "timeout"})
                return
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except ValueError:
                continue
            item = event.get("item") if isinstance(event, dict) else None
            if isinstance(item, dict) and item.get("type") == "function_call" and isinstance(item.get("call_id"), str):
                tool_names[item["call_id"]] = item.get("name")
            if (
                isinstance(item, dict)
                and item.get("type") == "function_call_output"
                and tool_names.get(item.get("call_id")) == DOCUMENT_SEARCH_TOOL
                and item.get("call_id") not in cited_calls
            ):
                cited_calls.add(item.get("call_id"))
                cited = _sources(item.get("output"))
                call_id = _safe(_SAFE_ID, item.get("call_id"))
                if cited and call_id:
                    yield _sse({"type": "sources", "id": call_id, "sources": cited})
            for out in _translate(event):
                finished = finished or out["type"] in ("done", "error")
                if out["type"] == "delta":
                    answer.append(out["text"])
                if out["type"] == "done":
                    if on_done is not None:
                        try:
                            await on_done("".join(answer), out["conversation_id"])
                        except Exception as error:
                            logger.warning("session_persist_failed", extra={"error_type": type(error).__name__})
                    # Same hash as the agent's turn logs: one query follows the call across both.
                    logger.info("chat_relay_completed", extra={"correlation": correlation_id(out["conversation_id"])})
                yield _sse(out)
            if finished:
                return
    except httpx.TimeoutException:
        logger.warning("chat_stream_failed", extra={"error_type": "TimeoutException"})
        yield _sse({"type": "error", "kind": "timeout"})
        return
    except Exception as error:
        logger.warning("chat_stream_failed", extra={"error_type": type(error).__name__})
        yield _sse({"type": "error", "kind": "upstream"})
        return
    if not finished:
        logger.warning("chat_stream_failed", extra={"error_type": "StreamEnded"})
        yield _sse({"type": "error", "kind": "upstream"})


def create_api_router(
    settings: ApiSettings,
    service: NotionOAuth,
    credential,
    http_client=None,
    workspace: WorkspaceService | None = None,
    documents=None,
) -> APIRouter:
    require_owner = _owner_check(settings)
    router = APIRouter(dependencies=[Depends(require_owner)])
    if workspace is not None:
        router.include_router(create_workspace_router(workspace, require_owner, documents))
        if documents is not None:
            from savant.bff_documents import create_documents_router

            router.include_router(create_documents_router(documents, workspace, require_owner))

    async def stored_session(body: ChatRequest) -> dict | None:
        """The session a chat belongs to; an unknown one is refused, a missing store is ignored."""
        if workspace is None or not body.session_id:
            return None
        try:
            return await workspace.session(body.session_id)
        except WorkspaceError:
            raise HTTPException(404) from None
        except Exception as error:
            logger.warning("workspace_failed", extra={"error_type": type(error).__name__})
            raise HTTPException(502) from None

    async def keep_turn(body: ChatRequest, answer: str, response_id: str | None) -> None:
        if workspace is not None and body.session_id:
            await workspace.record_turn(
                body.session_id, body.message, answer, voice=body.mode == "voice", response_id=response_id
            )

    # Both prefixes are served: /api for the PWA proxy, the bare path for direct calls.
    for prefix in ("", "/api"):

        @router.get(f"{prefix}/oauth/notion/start")
        async def start():
            try:
                url = await service.begin(settings.owner_id)
            except OAuthError:
                raise HTTPException(503) from None
            return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})

        @router.get(f"{prefix}/oauth/notion/status")
        async def status():
            try:
                connected = await service.get_access_token(settings.owner_id) is not None
            except OAuthError:
                raise HTTPException(503) from None
            return JSONResponse({"connected": connected}, headers={"Cache-Control": "no-store"})

    @router.post("/api/chat")
    async def chat(body: ChatRequest):
        payload = _agent_payload(body, stream=False, session=await stored_session(body))
        try:
            token = await credential.get_token(AGENT_TOKEN_SCOPE)
            headers = {"Authorization": f"Bearer {token.token}"}
            if http_client is not None:
                response = await http_client.post(settings.agent_responses_url, json=payload, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=AGENT_TIMEOUT_SECONDS) as client:
                    response = await client.post(settings.agent_responses_url, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            conversation_id = result["id"]
        except httpx.TimeoutException:
            logger.warning("chat_relay_timeout")
            raise HTTPException(504) from None
        except httpx.HTTPStatusError as error:
            # Only the numeric status is logged: never the agent's body, the URL or a token.
            logger.warning("chat_relay_failed", extra={"agent_status": error.response.status_code})
            raise HTTPException(502) from None
        except Exception as error:
            logger.warning("chat_relay_failed", extra={"error_type": type(error).__name__})
            raise HTTPException(502) from None
        logger.info("chat_relay_completed", extra={"correlation": correlation_id(conversation_id)})
        try:
            await keep_turn(body, _reply_text(result), conversation_id)
        except Exception as error:
            logger.warning("session_persist_failed", extra={"error_type": type(error).__name__})
        return JSONResponse(
            {"conversation_id": conversation_id, "reply": _reply_text(result)}, headers={"Cache-Control": "no-store"}
        )

    @router.post("/api/chat/stream")
    async def chat_stream(body: ChatRequest):
        """Same relay as /api/chat, but the answer is forwarded while the agent writes it."""
        payload = _agent_payload(body, stream=True, session=await stored_session(body))
        owned = http_client is None
        client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=AGENT_TIMEOUT_SECONDS))
        upstream = None
        try:
            token = await credential.get_token(AGENT_TOKEN_SCOPE)
            request = client.build_request(
                "POST", settings.agent_responses_url, json=payload, headers={"Authorization": f"Bearer {token.token}"}
            )
            upstream = await client.send(request, stream=True)
            upstream.raise_for_status()
        except BaseException as error:
            if upstream is not None:
                await upstream.aclose()
            if owned:
                await client.aclose()
            if isinstance(error, httpx.TimeoutException):
                logger.warning("chat_relay_timeout")
                raise HTTPException(504) from None
            if isinstance(error, httpx.HTTPStatusError):
                logger.warning("chat_relay_failed", extra={"agent_status": error.response.status_code})
                raise HTTPException(502) from None
            if not isinstance(error, Exception):
                raise
            logger.warning("chat_relay_failed", extra={"error_type": type(error).__name__})
            raise HTTPException(502) from None

        async def events():
            try:

                async def finished(answer, response_id):
                    await keep_turn(body, answer, response_id)

                async for chunk in _relay_events(upstream.aiter_lines(), finished):
                    yield chunk
            finally:
                await upstream.aclose()
                if owned:
                    await client.aclose()

        # no-transform and X-Accel-Buffering keep proxies from holding the stream back.
        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
        )

    speech_cache: dict = {}

    @router.post("/api/speech/token")
    async def speech_token():
        """A 10-minute Azure Speech token for the browser; no audio ever passes through the BFF."""
        if not settings.speech_endpoint:
            raise HTTPException(404)
        now = time.monotonic()
        if speech_cache.get("token") and now < speech_cache.get("until", 0):
            token, remaining = speech_cache["token"], int(speech_cache["expires"] - now)
        else:
            try:
                entra = await credential.get_token(SPEECH_SCOPE)
                headers = {"Authorization": f"Bearer {entra.token}", "Content-Length": "0"}
                url = settings.speech_endpoint + "/sts/v1.0/issueToken"
                if http_client is not None:
                    response = await http_client.post(url, headers=headers)
                else:
                    async with httpx.AsyncClient(timeout=10) as client:
                        response = await client.post(url, headers=headers)
                response.raise_for_status()
                token = response.text.strip()
                if not token:
                    raise ValueError("empty token")
            except httpx.TimeoutException:
                logger.warning("speech_token_failed", extra={"error_type": "TimeoutException"})
                raise HTTPException(504) from None
            except httpx.HTTPStatusError as error:
                logger.warning("speech_token_failed", extra={"agent_status": error.response.status_code})
                raise HTTPException(502) from None
            except Exception as error:
                logger.warning("speech_token_failed", extra={"error_type": type(error).__name__})
                raise HTTPException(502) from None
            speech_cache.update(
                token=token, until=now + SPEECH_TOKEN_REUSE_SECONDS, expires=now + SPEECH_TOKEN_LIFETIME_SECONDS
            )
            remaining = SPEECH_TOKEN_LIFETIME_SECONDS
        return JSONResponse(
            {"token": token, "region": settings.speech_region, "expires_in": remaining},
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/api/warmup")
    async def warmup():
        """Wake the agent with its tool-free probe so the first real message is not the cold one."""
        payload = {"input": WARMUP_PROMPT, "stream": False}
        try:
            token = await credential.get_token(AGENT_TOKEN_SCOPE)
            headers = {"Authorization": f"Bearer {token.token}"}
            if http_client is not None:
                response = await http_client.post(settings.agent_responses_url, json=payload, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=AGENT_TIMEOUT_SECONDS) as client:
                    response = await client.post(settings.agent_responses_url, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            ready = WARMUP_EXPECTED in _reply_text(result)
            # Foundry starts a new session (~13 s) for every new conversation. Handing the warm
            # conversation to the PWA lets its next first message continue it instead.
            warm = result.get("id") if isinstance(result.get("id"), str) else None
            warm = warm if ready and warm and re.fullmatch(_CONVERSATION_ID, warm) else None
        except httpx.TimeoutException:
            logger.warning("warmup_failed", extra={"error_type": "TimeoutException"})
            raise HTTPException(504) from None
        except httpx.HTTPStatusError as error:
            logger.warning("warmup_failed", extra={"agent_status": error.response.status_code})
            raise HTTPException(502) from None
        except Exception as error:
            logger.warning("warmup_failed", extra={"error_type": type(error).__name__})
            raise HTTPException(502) from None
        return JSONResponse(
            {"ready": ready, **({"conversation_id": warm} if warm else {})}, headers={"Cache-Control": "no-store"}
        )

    return router


def add_api(
    app: FastAPI,
    settings: ApiSettings,
    service: NotionOAuth,
    credential,
    http_client=None,
    workspace: WorkspaceService | None = None,
    documents=None,
) -> None:
    app.include_router(create_api_router(settings, service, credential, http_client, workspace, documents))
    if settings.pwa_origin:
        # Only needed when the PWA runs on another origin (local development).
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[settings.pwa_origin],
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Content-Type"],
        )
