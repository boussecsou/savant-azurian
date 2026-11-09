"""Direct Notion MCP: detached OAuth and durable conversational write approval."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import unicodedata
from typing import NotRequired

import httpx
import httpx2
from fastmcp import Client
from fastmcp.client.auth import BearerAuth
from langchain.mcp import as_langchain_tool
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.errors import GraphBubbleUp

from .. import documents, reliability, spotlight
from ..confirmations import NOTION_ID, confirmation_text, generic_confirmation, result_text, say
from ..correlation import correlation_id
from ..health import RUNTIME_SMOKE_PROMPT, is_runtime_probe
from ..identity import BASE_IDENTITY, FAST_PATH_INSTRUCTIONS, VOICE_STYLE, current_time_context
from ..language import clean_label, detect_language, language_note
from ..semantic_approval import approved_arguments, user_text
from ..semantic_ledger import ApprovalLedger, operation_digest
from . import DEFAULT_TOOLS
from . import ssh
from . import toolbox_policy
from .ssh_skill import SSH_INSTRUCTIONS
from .notion_policy import (NOTION_PRODUCTIVITY_INSTRUCTIONS, catalog_tools,
                            may_execute_without_approval, protected_tool_names, tool_fingerprint)

logger = logging.getLogger(__name__)
# Optional fields of the Notion MCP schema that only describe the caller ("for tracking only").
# Models often fill them; they change nothing the tool does, so they are never part of an
# operation: left in, they made every deletion or edit "too large to present clearly".
_TRACKING_ARGS = frozenset({"skill", "telemetry"})
_NOTION_ID = NOTION_ID
# What a model writes in `cursor` when it has none yet. Notion refuses every one of them, since
# the first page of a list takes no cursor at all.
_NO_CURSOR = frozenset({"", "null", "none", "undefined", "nil", "n/a"})


def _without_empty_cursor(call):
    """Drop a pagination cursor that is only a placeholder; a real one is opaque and is kept."""
    cursor = call["args"].get("cursor", "")
    if cursor is None or (isinstance(cursor, str) and cursor.strip().lower() in _NO_CURSOR):
        return {**call, "args": {k: v for k, v in call["args"].items() if k != "cursor"}}
    return call


async def use_tools() -> str:
    """Hand the request to the full agent, which has the tools (Notion, web search, VM, code, email)."""
    return "handed over"


USE_TOOLS = StructuredTool.from_function(coroutine=use_tools, name="use_tools",
                                         description=use_tools.__doc__)
FAST_PATH_TIMEOUT_SECONDS = 15.0


def _fast_path_allowed(state, rounds) -> bool:
    """Only a fresh turn with nothing pending: a confirmation always goes to the full agent."""
    return (rounds == 0 and not ssh.pending_live(state.get("ssh_pending")) and not state.get("notion_pending_actions")
            and not state.get("notion_pending_request"))


def _has_text(message) -> bool:
    content = message.content
    if isinstance(content, str):
        return bool(content.strip())
    return any(isinstance(part, dict) and str(part.get("text", "")).strip() for part in content or [])


def _without_warmup(messages):
    """Hide the BFF warm-up exchange that may open a conversation.

    The PWA continues the warm-up conversation to reuse its already started Foundry session;
    the probe ("Do not call any tools") must never reach the model as if the owner had said it.
    """
    if (len(messages) > 2 and messages[0].type == "human" and messages[0].content == RUNTIME_SMOKE_PROMPT
            and messages[1].type == "ai"):
        return messages[2:]
    return messages


SET_ASIDE_NOTES = {
    "declined": ("\nThe owner declined the operation that was waiting for confirmation: it was cancelled and "
                 "nothing was run. Acknowledge it briefly, then answer anything else their latest message asks."),
    "not_approved": ("\nThe owner's latest message did not approve the operation that was waiting for "
                     "confirmation: it was set aside and nothing was run. Answer their latest message. If they "
                     "still want that operation, call its tool again; the server will ask them again."),
}


def _set_aside(state) -> str:
    """Tells the model that a waiting operation was set aside this turn (and that nothing ran)."""
    return SET_ASIDE_NOTES.get(state.get("approval_set_aside") or "", "")


def _language(messages) -> str:
    """The "answer in the owner's language" line for this turn, from their messages (newest first)."""
    return language_note([user_text(m) for m in reversed(messages) if isinstance(m, HumanMessage)])


def _style(state) -> str:
    """The spoken-answer instructions for a voice turn; nothing for a text turn."""
    return VOICE_STYLE if state.get("channel") == "voice" else ""


class NotionChatState(MessagesState):
    notion_pending_request: NotRequired[str]
    notion_pending_actions: NotRequired[list[str]]
    approval_user_turn: NotRequired[dict]
    approval_last_turn: NotRequired[str]
    approval_stop: NotRequired[bool]
    approval_presentation: NotRequired[str]
    # This turn's message did not approve the waiting operation, which was set aside: "declined" or
    # "not_approved". Read only to tell the model; never a capability.
    approval_set_aside: NotRequired[str]
    # SSH: the one gated command waiting for the owner's confirmation in a later turn.
    ssh_pending: NotRequired[dict]
    # "voice" when this turn comes from the PWA's voice mode, else "text". Style only:
    # it never changes tools, policies or consent.
    channel: NotRequired[str]
    # The session's project (request metadata, set by the BFF). Scopes the document search; never a
    # model argument. None: no project, so no document search this turn.
    project_id: NotRequired[str | None]


def current_user_id(settings):
    """Return the key under which this caller's Notion grant is stored.

    With NOTION_OWNER_ID set (single-owner MVP) that fixed value is the key, so
    the BFF and the agent agree without knowing each other's Foundry identity.
    Only callers the Entra-protected endpoint already let in reach this code;
    in the cloud the per-request platform call identity must still be present.
    """
    from azure.ai.agentserver.core import get_request_context
    import os
    from urllib.parse import urlparse

    context = get_request_context()
    user = context.user_id
    hosted = bool(os.environ.get("FOUNDRY_HOSTING_ENVIRONMENT"))
    # This service declares Responses container protocol 2.0.0. Require its
    # per-request platform call identity as well as a user key in cloud.
    if hosted and not context.call_id:
        user = None
    if not user and not context.call_id and not os.environ.get("FOUNDRY_HOSTING_ENVIRONMENT"):
        if urlparse(settings.notion_oauth_callback_url).hostname in {"localhost", "127.0.0.1", "::1"}:
            user = settings.notion_local_user_id
    owner = getattr(settings, "notion_owner_id", "")
    if owner:
        key = owner if not hosted or context.call_id else None
    else:
        key = user
    if getattr(settings, "notion_identity_diagnostics", False):
        # Safe opt-in signal for a controlled Playground run: never log the ID.
        logger.info("NOTION_IDENTITY_DIAGNOSTIC=%s", "OK" if key else "MISSING")
    return key


# Listing the Notion catalog costs several round trips to mcp.notion.com, and the graph needs it up
# to three times per turn. The raw MCP definitions (names, schemas, annotations: no token) are kept
# for a few minutes per access token; the LangChain tools that carry the token are rebuilt each time.
NOTION_CATALOG_SECONDS = 600.0
_notion_catalogs: dict[str, tuple[float, list]] = {}


async def _notion_definitions(settings, access_token):
    key = hashlib.sha256(access_token.encode()).hexdigest()
    now = time.monotonic()
    cached = _notion_catalogs.get(key)
    if cached and cached[0] > now:
        return cached[1]
    client = Client(settings.notion_mcp_url, auth=BearerAuth(access_token), mode="legacy")
    discovered, seen, cursor = [], set(), None
    async with client:
        for _ in range(250):
            page = await client.list_tools_mcp(cursor=cursor, cache_mode="bypass")
            discovered.extend(page.tools)
            cursor = page.next_cursor
            if cursor is None:
                break
            if cursor in seen:
                raise RuntimeError("Notion catalog pagination is cyclic.")
            seen.add(cursor)
        else:
            raise RuntimeError("Notion catalog pagination limit reached.")
    for stale in [k for k, (until, _) in _notion_catalogs.items() if until <= now]:
        del _notion_catalogs[stale]
    _notion_catalogs[key] = (now + NOTION_CATALOG_SECONDS, discovered)
    return discovered


def forget_notion_catalog(access_token=None):
    """Drop cached catalogs: one token's (after a 401), or all of them."""
    if access_token is None:
        _notion_catalogs.clear()
    else:
        _notion_catalogs.pop(hashlib.sha256(access_token.encode()).hexdigest(), None)


async def discover_tools(settings, access_token):
    """Discover every page, fail on duplicate/cyclic catalogs, preserve schemas.

    FastMCP auto-pagination truncates cyclic cursors with a warning. Explicit
    pagination instead refuses partial catalogs. No token-bearing tool is cached
    globally or serialized into graph state: only the token-free definitions are
    (`_notion_definitions`), and a fresh client carries the token each time.
    """
    if settings.notion_mcp_url != "https://mcp.notion.com/mcp":
        raise RuntimeError("Chat OAuth must use the official Notion MCP endpoint.")
    discovered = await _notion_definitions(settings, access_token)
    client = Client(settings.notion_mcp_url, auth=BearerAuth(access_token), mode="legacy")
    adapted = [await as_langchain_tool(tool, client) for tool in discovered]
    catalog = catalog_tools(adapted)
    if settings.notion_tool_policy == "allowlist":
        requested = (*settings.notion_read_tool_names, *settings.notion_write_tool_names)
        if not requested or set(requested) - catalog.keys():
            raise RuntimeError("Configured Notion tools are unavailable.")
        return [catalog[name] for name in requested]
    return list(catalog.values())


def _resume_requested(messages):
    latest = next((m.content for m in reversed(messages) if m.type == "human"), "")
    if not isinstance(latest, str):
        return False
    normalized = "".join(c for c in unicodedata.normalize("NFD", latest.lower()) if not unicodedata.combining(c))
    return normalized.strip(" .!\n") in {"connecte", "c'est connecte", "connected", "continue", "connecte, continue", "c'est connecte, continue"}


def _safe_operation(operation):
    """Never persist/display credential-like arguments in an approval request."""
    encoded = json.dumps(operation, ensure_ascii=False, allow_nan=False)
    return not re.search(r'(?i)(access_token|refresh_token|client_secret|authorization|cookie|encryption_key|[?&](?:code|state)=|bearer\s|(?:secret_|ntn_)[A-Za-z0-9]{12,}|eyJ[A-Za-z0-9_-]{8,}\.)', encoded)


def _question(record, remaining):
    operation = record["operation"]
    described = toolbox_policy.describe(operation["name"], operation["args"])
    if described is not None:
        return AIMessage(content=described[1])
    lang = operation.get("lang")
    # Worded here from the validated arguments, never by the model: what is asked is what will run.
    return AIMessage(content=confirmation_text(operation, lang) or generic_confirmation(operation, lang))


def _latest_user_text(messages):
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return user_text(message)
    return None


def _title_from_result(result):
    """The page or database title in a notion-fetch result, made safe to show; None if absent."""
    content = result.content if isinstance(result, ToolMessage) else result
    if isinstance(content, list):
        content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    if not isinstance(content, str):
        return None
    try:
        data = json.loads(content)
        title = data.get("title") if isinstance(data, dict) else None
    except ValueError:
        match = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', content[:2000])
        try:
            title = json.loads('"' + match.group(1) + '"') if match else None
        except ValueError:
            title = None
    return clean_label(title)


async def _labels_for(call, catalog):
    """Titles of the pages a protected call targets, read with notion-fetch, only to word the question.

    Best effort and display only: a missing tool, a timeout or an odd answer leaves the label out.
    """
    args = call["args"]
    ids = args.get("page_ids") or args.get("database_ids") or ([args["page_id"]] if args.get("page_id") else [])
    fetch = catalog.get("notion-fetch")
    if fetch is None or not isinstance(ids, list) or not 0 < len(ids) <= 3:
        return {}
    ids = [i for i in ids if isinstance(i, str) and _NOTION_ID.fullmatch(i)]

    async def one(notion_id):
        try:
            return notion_id, _title_from_result(await asyncio.wait_for(fetch.ainvoke({"id": notion_id}), 4))
        except Exception:
            return notion_id, None

    return {notion_id: title for notion_id, title in await asyncio.gather(*(one(i) for i in ids)) if title}


def _presentable(operation):
    """Never approve a scope whose full details cannot fit in a concise prompt."""
    name, args = operation["name"], operation["args"]
    inner = toolbox_policy.effective_call(name, args)[0]
    if toolbox_policy.outlook_operation(inner) in toolbox_policy.OUTLOOK_SENDS | toolbox_policy.OUTLOOK_DELETES:
        # Sends and deletes are shown in full by the server or refused: never approved blind.
        return toolbox_policy.describe(name, args) is not None
    if name in {"notion-delete-pages", "notion-delete-databases"}:
        field = "page_ids" if name == "notion-delete-pages" else "database_ids"
        ids = args.get(field)
        return set(args) <= {field, "user_confirmed", "instructions_version"} and isinstance(ids, list) and 0 < len(ids) <= 20 and all(
            isinstance(value, str) and _NOTION_ID.fullmatch(value) for value in ids)
    if name == "notion-update-page" and args.get("command") == "update_content":
        updates = args.get("content_updates")
        page = args.get("page_id")
        return (isinstance(page, str) and _NOTION_ID.fullmatch(page) is not None
            and set(args) <= {"page_id", "command", "content_updates", "allow_async", "instructions_version"}
            and isinstance(updates, list) and bool(updates) and all(
            isinstance(item, dict) and isinstance(item.get("old_str"), str)
            and isinstance(item.get("new_str"), str) and set(item) <= {"old_str", "new_str", "replace_all_matches"}
            for item in updates) and sum(len(item["old_str"]) + len(item["new_str"]) for item in updates) <= 300)
    if name == "notion-update-page" and args.get("command") == "replace_content":
        page = args.get("page_id")
        return (isinstance(page, str) and _NOTION_ID.fullmatch(page) is not None
                and set(args) <= {"page_id", "command", "new_str", "allow_async", "instructions_version"}
                and isinstance(args.get("new_str"), str) and len(args["new_str"]) <= 300)
    return len(json.dumps(args, ensure_ascii=False, sort_keys=True)) <= 300


def _notice(code, message):
    return AIMessage(content=json.dumps({"code": code, "message": message, "retryable": False}, ensure_ascii=False))


def build_direct_chat_graph(settings, model_factory, checkpointer, oauth, *, identity_provider=None, load_toolbox=None, ledger=None, guardrail=None, ssh_runner=None, ssh_judge=None,
                            fast_model_factory=None, document_search=None):
    """Use ordinary END turns, not native interrupts, for text confirmations.

    Only the entry node may authorize an existing action. Model output and tool
    content cannot reach that path. Execution always uses the immutable ledger
    operation, with an atomic claim committed before external I/O.
    """
    if checkpointer is None:
        raise ValueError("Conversational approval requires a checkpointer.")
    identity_provider = identity_provider or (lambda: current_user_id(settings))
    ledger = ledger or (ApprovalLedger(oauth.store) if hasattr(oauth, "store") else None)
    ssh_tools = ssh.build_ssh_tools() if ssh_runner is not None else []

    async def evaluate(record, text, remaining):
        if guardrail is None:
            return "CLARIFY"
        return await guardrail.evaluate(operation=record["operation"],
            proposal=_question(record, remaining).content, user_message=text,
            context={"pending_count": remaining, "scope": "current operation only"})

    toolbox_state = {"error": None, "until": 0.0}
    background = set()

    async def fetch_toolbox():
        """The toolbox catalog, or the error that kept it away. A failure is remembered for a short
        cooldown: without that, a toolbox that is down made every turn wait for its timeout again."""
        if load_toolbox is None:
            return None
        if toolbox_state["error"] is not None and time.monotonic() < toolbox_state["until"]:
            return toolbox_state["error"]
        try:
            result = await asyncio.wait_for(load_toolbox(), reliability.TOOLBOX_TIMEOUT_SECONDS)
        except Exception as error:
            toolbox_state.update(error=error, until=time.monotonic() + reliability.TOOLBOX_COOLDOWN_SECONDS)
            return error
        toolbox_state["error"] = None
        return result

    def warm_toolbox():
        """Start loading the toolbox in the background (the warm-up request), so the first real turn finds it ready."""
        if load_toolbox is None:
            return
        task = asyncio.create_task(fetch_toolbox())
        background.add(task)
        task.add_done_callback(background.discard)

    def project_tools(project):
        """The document search for this turn's project, or nothing (no search configured, no project)."""
        if document_search is None or not project:
            return []
        try:
            return [documents.build_search_tool(document_search, project)]
        except ValueError:
            return []

    async def load_tools(timings=None, project=None):
        user = identity_provider()
        started = time.perf_counter()

        async def token_step():
            value = await oauth.get_access_token(user) if user else None
            if timings is not None:
                timings["token_ms"] = round((time.perf_counter() - started) * 1000)
            return value

        async def toolbox_step():
            try:
                return await fetch_toolbox()
            finally:
                if timings is not None:
                    timings["toolbox_ms"] = round((time.perf_counter() - started) * 1000)

        # The OAuth store and the toolbox are independent: load them side by side.
        token, toolbox_result = await asyncio.gather(token_step(), toolbox_step())
        tools, protected, notion_names = [*DEFAULT_TOOLS, *ssh_tools, *project_tools(project)], set(), set()
        toolbox_names, toolbox_failed = set(), False
        if load_toolbox is not None:
            try:
                if isinstance(toolbox_result, BaseException):
                    raise toolbox_result
                toolbox_tools, platform_protected = toolbox_result
            except Exception as error:
                # An optional toolbox must not take the whole chat down (Notion, SSH): carry on without it
                # and say so to the model. Only the error type and an HTTP status are logged.
                toolbox_tools, platform_protected, toolbox_failed = [], (), True
                logger.warning("toolbox_unavailable error_type=%s status=%s code=%s detail=%s", type(error).__name__,
                               getattr(getattr(error, "response", None), "status_code", None),
                               _error_code(error), _redacted(error))
            # The text gate decides per call (toolbox_policy): known reads run freely, everything
            # else, including any unrecognised tool, is protected. `call_tool` is judged by the tool
            # it dispatches to, never by its own name.
            tools.extend(t for t in toolbox_tools if t.name not in {t.name for t in DEFAULT_TOOLS})
            toolbox_names = {t.name for t in toolbox_tools} - {t.name for t in DEFAULT_TOOLS}
            protected.update(platform_protected or ())
        if token:
            try:
                notion_started = time.perf_counter()
                notion_tools = await asyncio.wait_for(discover_tools(settings, token),
                                                      reliability.LOADER_TIMEOUT_SECONDS)
                if timings is not None:
                    timings["notion_ms"] = round((time.perf_counter() - notion_started) * 1000)
                tools.extend(notion_tools)
                notion_names.update(tool.name for tool in notion_tools)
                protected.update(protected_tool_names(notion_tools))
                protected.update(settings.notion_write_tool_names)
            except (httpx.HTTPStatusError, httpx2.HTTPStatusError) as exc:
                if exc.response.status_code != 401:
                    raise
                forget_notion_catalog(token)
                await oauth.invalidate(user)
                token = None
        if not token:
            async def connect_notion():
                """Connect Notion before using its tools."""
                return await oauth.begin(user) if user else "Notion unavailable: user identity missing from the request."
            tools.append(StructuredTool.from_function(coroutine=connect_notion, name="connect_notion", description="Connect Notion when a requested task requires it. Returns a personal consent link; no Notion access before consent."))
        catalog_tools(tools)
        return tools, protected, bool(token), notion_names, toolbox_names, toolbox_failed

    async def enter_turn(state, config):
        update = await _enter_turn(state, config)
        return {"approval_set_aside": "", **update}

    async def _enter_turn(state, config):
        if is_runtime_probe(state["messages"]):
            return {"approval_stop": False}
        user = identity_provider()
        thread = config.get("configurable", {}).get("thread_id", "")
        if not user or not thread:
            return {"messages": [_notice("identity_required", "Notion unavailable: user identity missing or owner not authorized.")], "approval_stop": True}
        if ledger is not None and not await ledger.bind_thread(user, thread):
            return {"messages": [_notice("identity_mismatch", "This conversation belongs to another owner.")], "approval_stop": True}
        turn = state.get("approval_user_turn")
        if turn is None:
            # Local graph API only. Production host always supplies an envelope
            # derived solely from current request role=user items.
            last = state["messages"][-1]
            turn = {"id": last.id, "text": user_text(last)}
        turn_id = turn.get("id") or ""
        logger.info("turn_start correlation=%s", correlation_id(turn_id))
        pending = state.get("notion_pending_actions", [])
        if not pending:
            # A replay must not become a fresh request to the generative model.
            # Consult the durable last presentation even when a checkpoint lost
            # its pending list; terminal authorizations cannot be reused.
            presented = await ledger.presentation(user, thread) if ledger else None
            # Only a direct reply to the presented question can be a replay. Later turns of the
            # conversation chain from a newer response: judging them again cost one more model call
            # per turn, and a "no" or a "yes" meant for something else blocked the turn.
            previous_id = turn.get("previous_response_id")
            if presented and (not previous_id or previous_id == presented["response_id"]):
                previous = await ledger.get(user, thread, presented["action_id"])
                if previous and (previous["status"] == "pending" or
                                 await evaluate(previous, turn.get("text"), 0) != "CLARIFY"):
                    return {"approval_stop": True, "approval_last_turn": turn_id,
                            "messages": [_notice("no_pending_approval", "No confirmable operation in this turn; nothing was run.")]}
            return {"approval_stop": False, "approval_last_turn": turn_id}
        blocked = {"approval_stop": True}
        if ledger is None or not turn_id or turn_id == state.get("approval_last_turn"):
            return {**blocked, "messages": [_notice("confirmation_required", "A new explicit user message is required.")]}
        record = await ledger.get(user, thread, pending[0])
        if not record or record["status"] != "pending":
            return {**blocked, "notion_pending_actions": [], "approval_last_turn": turn_id,
                    "messages": [_notice("approval_unavailable", "Authorization expired, already used or outcome uncertain. Nothing was repeated; check the remote state.")]}
        presented = await ledger.presentation(user, thread)
        # Trust the server's durable presentation, never inferred dialogue or
        # an action identifier supplied by the classifier/user. An explicitly
        # stale response link is blocked even if the semantic verdict is yes.
        linked = (presented is not None and
                  presented["action_id"] == record["action_id"] and
                  presented["response_id"] == state.get("approval_presentation") and
                  (not turn.get("previous_response_id") or
                   turn["previous_response_id"] == presented["response_id"]))
        trusted_transport = (turn.get("source") != "responses" or
                             bool(turn.get("previous_response_id") or turn.get("conversation")))
        text = turn.get("text")
        # Only a real owner message, answering the presented question, is judged. Anything else (a
        # stale link, an untrusted transport, no text, no judge) keeps the operation waiting.
        judged = linked and trusted_transport and guardrail is not None and isinstance(text, str) and bool(text.strip())
        decision = await evaluate(record, text, len(pending)) if judged else "CLARIFY"
        # The language of the request that created the operation, not of a bare "yes" or a button's text.
        lang = record["operation"].get("lang") or detect_language(turn.get("text"))
        logger.info("approval_decision correlation=%s decision=%s linked=%s trusted=%s",
                    correlation_id(turn_id), decision, linked, trusted_transport)
        if decision != "APPROVE" and not judged:
            if not await ledger.present(user, thread, record["action_id"], turn_id):
                return {**blocked, "approval_last_turn": turn_id,
                        "messages": [_notice("approval_conflict", "Another proposal is pending; clarify its scope first.")]}
            return {**blocked, "approval_last_turn": turn_id, "approval_presentation": turn_id,
                    "messages": [_question(record, len(pending))]}
        if decision != "APPROVE":
            # The owner's own answer, and not a yes: the waiting operation is set aside (nothing runs) and the message goes to the
            # model like any other, so the owner can refuse, ask a question or change the subject
            # without the question coming back. Wanting the operation again means a new proposal,
            # worded and judged again by the server.
            for action in pending:
                await ledger.reject(user, thread, action)
            return {"approval_stop": False, "notion_pending_actions": [], "approval_last_turn": turn_id,
                    "approval_set_aside": "declined" if decision == "REJECT" else "not_approved"}
        # Refresh account access and tool schema before claiming. No fallback,
        # changed parameters or fresh model interpretation can inherit consent.
        try:
            tools, _, _, _, _, _ = await load_tools()
            tool = catalog_tools(tools).get(record["operation"]["name"])
        except Exception:
            return {**blocked, "approval_last_turn": turn_id, "messages": [_notice("tools_unavailable", "Tool catalog unavailable; nothing was written.")]}
        operation = record["operation"]
        if tool is None or tool_fingerprint(tool) != operation["fingerprint"] or operation_digest(operation) != record["digest"]:
            for action in pending:
                await ledger.reject(user, thread, action)
            return {**blocked, "notion_pending_actions": [], "messages": [_notice("operation_changed", "Tool missing or schema changed; a new proposal is needed.")]}
        if not await ledger.claim(user, thread, record["action_id"], record["digest"], message_id=turn_id,
                                  presentation_id=presented["response_id"]):
            return {**blocked, "notion_pending_actions": [], "messages": [_notice("approval_consumed", "Authorization already used; nothing was repeated.")]}
        call = {"name": operation["name"], "args": operation["args"], "id": record["action_id"], "type": "tool_call"}
        try:
            result = await tool.ainvoke(call, config)
            failed = isinstance(result, ToolMessage) and result.status == "error"
            await ledger.finish(user, thread, record["action_id"], "failed" if failed else "succeeded")
        except Exception:
            await ledger.finish(user, thread, record["action_id"], "unknown")
            # Do not continue a batch when the outcome of an operation is unknown.
            for action in pending[1:]:
                await ledger.reject(user, thread, action)
            return {**blocked, "notion_pending_actions": [], "approval_last_turn": turn_id,
                    "messages": [_notice("write_result_unknown", "Uncertain result. Nothing is repeated automatically; check the remote state before any new request.")]}
        remaining = pending[1:]
        if failed:
            for action in remaining:
                await ledger.reject(user, thread, action)
            remaining = []
        # Tool output remains data, never a new instruction or confirmation.
        # A fresh model call is intentionally not made after a protected write.
        answer = AIMessage(content=result_text(operation, lang, failed),
                           additional_kwargs={"savant_status": "tool_error" if failed else "tool_returned"})
        output = [answer]
        if remaining:
            next_record = await ledger.get(user, thread, remaining[0])
            if next_record and next_record["status"] == "pending":
                if await ledger.present(user, thread, next_record["action_id"], turn_id):
                    output.append(_question(next_record, len(remaining)))
                else:
                    remaining = []
                    output.append(_notice("approval_conflict", "Competing proposals; clarification needed."))
            else:
                remaining = []
        return {**blocked, "notion_pending_actions": remaining, "approval_last_turn": turn_id, "approval_presentation": turn_id, "messages": output}

    async def call_model(state):
        messages = state["messages"]
        if is_runtime_probe(messages):
            warm_toolbox()
            return {"messages": [await model_factory(()).ainvoke([SystemMessage(content=BASE_IDENTITY + _style(state)), *messages])]}
        messages = _without_warmup(messages)
        correlation = correlation_id(state.get("approval_last_turn"))
        rounds = reliability.tool_rounds_this_turn(messages)
        # Older tool results shrink to a marker in what the model reads; the saved thread keeps them.
        messages = reliability.compact_history(messages)
        clock = current_time_context()
        if fast_model_factory is not None and _fast_path_allowed(state, rounds):
            # Fast path: no tool schemas, no reasoning. A plain answer ends the turn; a call to
            # `use_tools` (or any failure) falls through to the full agent below. Nothing the fast
            # model returns can act: it has no tool but the hand-over.
            fast_started = time.perf_counter()
            try:
                routed = await asyncio.wait_for(
                    fast_model_factory((USE_TOOLS,)).ainvoke(
                        [SystemMessage(content=BASE_IDENTITY + FAST_PATH_INSTRUCTIONS + _language(messages) + clock
                                       + _set_aside(state) + _style(state)), *messages]),
                    FAST_PATH_TIMEOUT_SECONDS)
            except Exception as error:
                routed = None
                logger.warning("fast_path_failed correlation=%s error_type=%s", correlation, type(error).__name__)
            fast_ms = round((time.perf_counter() - fast_started) * 1000)
            if routed is not None and not routed.tool_calls and _has_text(routed):
                logger.info("turn_timing correlation=%s round=1 path=fast fast_ms=%d", correlation, fast_ms)
                logger.info("turn_end correlation=%s path=fast outcome=answered", correlation)
                return {"messages": [routed]}
            logger.info("turn_timing correlation=%s round=1 path=handover fast_ms=%d", correlation, fast_ms)
        try:
            timings = {}
            load_started = time.perf_counter()
            tools, _, connected, _, _, toolbox_failed = await load_tools(timings, state.get("project_id"))
            timings["load_ms"] = round((time.perf_counter() - load_started) * 1000)
        except Exception as error:
            logger.warning("turn_end correlation=%s outcome=tools_unavailable error_type=%s", correlation, type(error).__name__)
            return {"messages": [_notice("tools_unavailable", "Tools unavailable; no result to report.")]}
        # Stable instructions first (the language line only changes with the owner's language), then the
        # clock and per-turn parts (voice style, notices) last, so consecutive
        # turns share a long identical prefix that Azure OpenAI can serve from its prompt cache.
        searchable = any(tool.name == documents.TOOL_NAME for tool in tools)
        context = (BASE_IDENTITY + "\n" + NOTION_PRODUCTIVITY_INSTRUCTIONS + (SSH_INSTRUCTIONS if ssh_tools else "")
                   + (documents.INSTRUCTIONS if searchable else "")
                   + ("\n" + toolbox_policy.OUTLOOK_INSTRUCTIONS if load_toolbox is not None and not toolbox_failed else "")
                   + ("\nThe toolbox (Outlook, web search, code interpreter) is unavailable for this request: "
                      "if the owner asks for one of them, say it is unavailable right now. Never invent results."
                      if toolbox_failed else "")
                   + _language(messages) + clock + _set_aside(state) + _style(state))
        if rounds >= reliability.MAX_TOOL_ROUNDS:
            logger.warning("turn_end correlation=%s outcome=loop_guard rounds=%d", correlation, rounds)
            # Bounded turn: never loop on tools. The owner decides whether to continue.
            return {"messages": [AIMessage(content=(
                f"I stopped after {reliability.MAX_TOOL_ROUNDS} tool steps without reaching an answer. "
                "Tell me how to narrow the request, or say \"continue\" to let me go on."))]}
        pending = state.get("notion_pending_request", "")
        if pending and _resume_requested(messages):
            if not connected:
                connect = next(t for t in tools if t.name == "connect_notion")
                return {"messages": [AIMessage(content=_consent_text(await connect.ainvoke({})))]}
            context += "\nThe user has completed Notion OAuth. Continue their pending request: " + pending
        model_started = time.perf_counter()
        response = await model_factory(tools).ainvoke([SystemMessage(content=context), *messages])
        timings["model_ms"] = round((time.perf_counter() - model_started) * 1000)
        # Durations only (no content): where a slow turn spends its time.
        logger.info("turn_timing correlation=%s round=%d %s", correlation, rounds + 1,
                    " ".join(f"{key}={value}" for key, value in sorted(timings.items())))
        if response.tool_calls:
            logger.info("turn_step correlation=%s path=tool round=%d tools=%s", correlation, rounds + 1,
                        ",".join(sorted({call["name"] for call in response.tool_calls}))[:200])
        else:
            logger.info("turn_end correlation=%s path=%s outcome=answered", correlation, "tool" if rounds else "direct")
        latest_human = max((i for i, m in enumerate(messages) if m.type == "human"), default=-1)
        failed = any(m.type == "tool" and m.status == "error" for m in messages[latest_human + 1:])
        finished = connected and pending and _resume_requested(messages) and not response.tool_calls and not failed
        return {"messages": [response], "notion_pending_request": "" if finished else pending}

    async def call_tools(state, config):
        calls = state["messages"][-1].tool_calls
        if any(call["name"] == "connect_notion" for call in calls):
            user = identity_provider()
            url = await oauth.begin(user) if user else "Notion unavailable: user identity missing from the request."
            results = [ToolMessage(content="Notion connection pending; no tool was run.", name=call["name"], tool_call_id=call["id"], status="success" if call["name"] == "connect_notion" else "error") for call in calls]
            original = state.get("notion_pending_request") or next((m.content for m in reversed(state["messages"]) if m.type == "human"), "")
            return {"messages": [*results, AIMessage(content=_consent_text(url))], "notion_pending_request": original if isinstance(original, str) else ""}
        try:
            tools, protected, _, notion_names, toolbox_names, _ = await load_tools(project=state.get("project_id"))
        except Exception:
            return {"messages": [*[ToolMessage(content=_tool_error(RuntimeError()), tool_call_id=c["id"], name=c["name"], status="error") for c in calls], _notice("tools_unavailable", "Tool catalog unavailable; no call was run.")]}
        catalog = catalog_tools(tools)
        calls = [_without_empty_cursor(c) if c["name"] in notion_names else c for c in calls]
        # Passages of the owner's documents are outside data too: marked, never instructions.
        untrusted_names = notion_names | toolbox_names | {documents.TOOL_NAME}

        def is_automatic_write(call):
            tool = catalog.get(call["name"])
            return tool is not None and call["name"] in notion_names and may_execute_without_approval(tool, call["args"])

        async def execute(call, user, thread):
            """One call, bounded in time. Always returns exactly one ToolMessage."""
            def failure(text):
                return ToolMessage(content=text, name=call["name"], tool_call_id=call["id"], status="error")

            action_id = None
            tool = catalog.get(call["name"])
            if is_automatic_write(call):
                if ledger is None or not user or not thread or not state.get("approval_last_turn"):
                    return failure("Write blocked: durable storage unavailable.")
                args = approved_arguments(tool, call["args"])
                operation = {"name": tool.name, "args": args, "fingerprint": tool_fingerprint(tool)}
                action_id = hashlib.sha256(json.dumps([thread, state["approval_last_turn"], call["id"], operation], sort_keys=True).encode()).hexdigest()
                if not await ledger.claim_automatic(user, thread, action_id, operation_digest(operation)):
                    return failure("This write was already handled or its outcome is uncertain; check the page.")
                call = {**call, "args": args}
            elif tool is not None:
                # A wrong argument is answered here, precisely, instead of after a round trip to the service.
                problem = reliability.schema_problem(tool, call["args"])
                if problem:
                    logger.info("tool_arguments_invalid tool=%s", call["name"])
                    return failure(json.dumps({"code": "invalid_arguments", "message": problem, "retryable": False},
                                              ensure_ascii=False))
            # A write (action_id) runs once; a read may be retried once on a transient failure.
            attempts = 1 if action_id else 1 + reliability.READ_RETRIES
            result = None
            for attempt in range(attempts):
                transient = False
                try:
                    result = (await asyncio.wait_for(ToolNode(tools, handle_tool_errors=_tool_error).ainvoke(
                        {"messages": [AIMessage(content="", tool_calls=[call])]}, config),
                        reliability.TOOL_TIMEOUT_SECONDS))["messages"][0]
                    transient = result.status == "error" and reliability.is_retryable_result(result.content)
                    if result.status == "error":
                        # The tool name only: what the tool answered may hold the owner's content.
                        logger.warning("tool_failed tool=%s", call["name"])
                    if action_id:
                        await ledger.finish_automatic(user, thread, action_id,
                                                      "failed" if result.status == "error" else "succeeded")
                except GraphBubbleUp:
                    raise
                except Exception as error:
                    logger.warning("tool_failed tool=%s error_type=%s", call["name"], type(error).__name__)
                    if action_id:
                        await ledger.finish_automatic(user, thread, action_id, "unknown")
                        result = failure("Uncertain result; check the page before retrying.")
                    else:
                        transient = reliability.is_transient(error)
                        result = failure(_tool_error(error))
                if not transient or attempt == attempts - 1:
                    break
                logger.info("tool_retry tool=%s attempt=%d", call["name"], attempt + 2)
                await asyncio.sleep(reliability.retry_delay(attempt, reliability.retry_after_of(result.content)))
            if call["name"] in untrusted_names and result.status != "error":
                # Bounded, then marked as outside data. Our own error messages stay plain JSON.
                result = spotlight.wrap(reliability.cap_result(result), call["name"])
            return result

        async def run_safe(safe_calls):
            user = identity_provider()
            thread = config.get("configurable", {}).get("thread_id", "")
            results = [None] * len(safe_calls)
            # Reads do not depend on each other: run them side by side, a few at a time. Automatic writes
            # claim the ledger one by one, after the reads, in the order the model asked for them.
            gate = asyncio.Semaphore(reliability.MAX_PARALLEL_READS)

            async def bounded(call):
                async with gate:
                    return await execute(call, user, thread)

            reads = [i for i, call in enumerate(safe_calls) if not is_automatic_write(call)]
            for index, outcome in zip(reads, await asyncio.gather(*(bounded(safe_calls[i]) for i in reads))):
                results[index] = outcome
            for index, call in enumerate(safe_calls):
                if results[index] is not None:
                    continue
                if any(r is not None and r.status == "error" for r in results[:index]):
                    results[index] = ToolMessage(content="Not run after an earlier operation failed.",
                                                 name=call["name"], tool_call_id=call["id"], status="error")
                else:
                    results[index] = await execute(call, user, thread)
            return results

        def gated(call):
            if call["name"] in toolbox_names:
                return call["name"] in protected or toolbox_policy.requires_approval(call["name"], call["args"])
            return call["name"] in protected and (
                call["name"] not in notion_names or call["name"] in settings.notion_write_tool_names or
                not may_execute_without_approval(catalog[call["name"]], call["args"]))

        writes = [c for c in calls if gated(c)]
        if writes:
            # Safe calls can proceed; protected calls remain in the durable gate.
            user = identity_provider()
            thread = config.get("configurable", {}).get("thread_id", "")
            pending = []
            lang = detect_language(_latest_user_text(state["messages"])) or "en"
            if ledger is not None and user and thread:
                for call in writes:
                    tool = catalog[call["name"]]
                    arguments = approved_arguments(tool, {k: v for k, v in call["args"].items() if k not in _TRACKING_ARGS})
                    if call["name"] in {"notion-delete-pages", "notion-delete-databases"}:
                        # The provider requires this flag. Bind the exact value to
                        # the proposal, but invoke it only after the owner's approval.
                        arguments = approved_arguments(tool, {**arguments, "user_confirmed": True})
                    operation = {"name": call["name"], "args": arguments,
                                 "description": tool.description, "fingerprint": tool_fingerprint(tool),
                                 # Display only: the owner's language and the titles read for the question.
                                 "lang": lang, "labels": await _labels_for({"args": arguments}, catalog)}
                    if not _presentable(operation):
                        # Names only, never values: which argument made the scope unclear.
                        logger.warning("operation_not_presentable tool=%s arg_keys=%s", call["name"], ",".join(sorted(arguments)))
                        for action in pending:
                            await ledger.reject(user, thread, action)
                        return {"messages": [*[ToolMessage(content="Operation blocked: scope too large to confirm clearly.",
                            tool_call_id=c["id"], name=c["name"], status="error") for c in calls],
                            AIMessage(content=say("unclear", lang))]}
                    if not _safe_operation(operation):
                        break
                    # Stable across re-execution of the same checkpoint/tool call.
                    action_id = hashlib.sha256(json.dumps([thread, state.get("approval_last_turn"), call["id"], operation], sort_keys=True).encode()).hexdigest()
                    record = await ledger.create(user, thread, operation, action_id)
                    if record["status"] != "pending":
                        break
                    pending.append(record["action_id"])
                else:
                    records = [await ledger.get(user, thread, action) for action in pending]
                    safe_calls = [c for c in calls if c not in writes]
                    safe_results = []
                    if safe_calls:
                        safe_results = await run_safe(safe_calls)
                    results_by_id = {result.tool_call_id: result for result in safe_results}
                    results = [results_by_id.get(c["id"]) or ToolMessage(
                        content="Deferred pending confirmation.", tool_call_id=c["id"], name=c["name"])
                        for c in calls]
                    if any(result.status == "error" for result in safe_results):
                        for action in pending:
                            await ledger.reject(user, thread, action)
                        return {"messages": [*results, _notice("batch_failed", "An operation failed; no deletion was started.")]}
                    presentation_id = state.get("approval_last_turn", "")
                    if not await ledger.present(user, thread, pending[0], presentation_id):
                        for action in pending:
                            await ledger.reject(user, thread, action)
                        return {"messages": [*results, _notice("approval_conflict", "An earlier proposal is waiting for clarification.")]}
                    return {"messages": [*results, _question(records[0], len(pending))],
                            "notion_pending_actions": pending, "approval_presentation": presentation_id}
            for action in pending:
                await ledger.reject(user, thread, action)
            return {"messages": [*[ToolMessage(content="Write blocked.", tool_call_id=c["id"], name=c["name"], status="error") for c in calls], _notice("approval_unavailable", "Write blocked: durable storage missing, operation consumed or sensitive parameters.")]}
        # Execution-time classification is authoritative even if the catalog
        # changed since the model was bound. Unknown names fail in ToolNode.
        results = await run_safe(calls)
        if any(result.status == "error" and call["name"] in notion_names and
               call["name"] in catalog and may_execute_without_approval(catalog[call["name"]], call["args"])
               for call, result in zip(calls, results)):
            return {"messages": [*results, _notice("tool_execution_failed", "An operation failed or its outcome is uncertain; check before retrying.")]}
        return {"messages": results}

    async def run_ssh(state, config):
        """ssh_exec calls only: judge, gate, then run side by side. Mixed batches are refused so each
        gate stays unambiguous; at most one command waits for the owner's confirmation."""
        calls = state["messages"][-1].tool_calls
        if any(call["name"] not in ssh.SSH_TOOL_NAMES for call in calls) or len(calls) > ssh.MAX_PARALLEL_COMMANDS:
            return {"messages": [ssh.error_message(call, "Call ssh_exec alone, at most "
                                                   f"{ssh.MAX_PARALLEL_COMMANDS} commands per step; nothing was "
                                                   "run.") for call in calls]}
        user = identity_provider()
        thread = config.get("configurable", {}).get("thread_id", "")
        turn, pending = state.get("approval_last_turn"), state.get("ssh_pending")

        def decide(call, verdict=None):
            return ssh.decide(call["args"], user=user, thread=thread, turn=turn, pending=pending, verdict=verdict)

        decisions = [decide(call) for call in calls]
        to_judge = [i for i, decision in enumerate(decisions) if decision.action == "judge"]
        if to_judge:
            owner_message = _latest_user_text(state["messages"])
            # What the turn read so far (web, Notion) is a hint for the judge, never a block by itself.
            outside = spotlight.tainted_turn(state["messages"])

            async def verdict_of(call):
                if ssh_judge is None:
                    return "CONFIRM"
                started = time.monotonic()
                verdict = await ssh_judge.judge(command=call["args"]["command"].strip(),
                                                reason=call["args"].get("reason", ""),
                                                owner_message=owner_message, outside_content=outside)
                logger.info("ssh_verdict digest=%s verdict=%s outside=%s ms=%d",
                            ssh.command_digest(user, thread, call["args"]["command"])[:12], verdict, outside,
                            round((time.monotonic() - started) * 1000))
                return verdict

            verdicts = await asyncio.gather(*(verdict_of(calls[i]) for i in to_judge))
            for i, verdict in zip(to_judge, verdicts):
                decisions[i] = decide(calls[i], verdict)
        update, waiting = {}, False
        for i, decision in enumerate(decisions):
            if decision.action == "confirm":
                if waiting:
                    # One pending slot: the owner answers one question at a time.
                    decisions[i] = ssh.Decision("refuse", "Nothing was run: another command of this step already "
                                                          "waits for confirmation. Propose this one after it.")
                    continue
                waiting = True
            if decision.pending is not None and (decision.pending or "ssh_pending" not in update):
                update["ssh_pending"] = decision.pending

        async def execute(call):
            started = time.monotonic()
            digest = ssh.command_digest(user, thread, call["args"]["command"])[:12]
            try:
                outcome = await ssh_runner.run(call["args"]["command"].strip())
            except ssh.SshError as error:
                logger.warning("ssh_exec failed digest=%s", digest)
                return ssh.error_message(call, str(error))
            elapsed = round((time.monotonic() - started) * 1000)
            logger.info("ssh_exec digest=%s exit=%s ms=%d", digest, outcome.exit_status, elapsed)
            return ssh.result_message(call, outcome, elapsed)

        runs = [i for i, decision in enumerate(decisions) if decision.action == "run"]
        outcomes = dict(zip(runs, await asyncio.gather(*(execute(calls[i]) for i in runs))))
        results = []
        for i, (call, decision) in enumerate(zip(calls, decisions)):
            if i in outcomes:
                results.append(outcomes[i])
            elif decision.action == "confirm":
                results.append(ToolMessage(content=decision.message, name=call["name"], tool_call_id=call["id"]))
            else:
                results.append(ssh.error_message(call, decision.message))
        return {"messages": results, **update}

    def route_model(state):
        calls = getattr(state["messages"][-1], "tool_calls", None)
        if not calls:
            return END
        return "ssh" if ssh_runner is not None and any(call["name"] in ssh.SSH_TOOL_NAMES for call in calls) else "tools"

    def safe_execution_node(node):
        async def guarded(state, config):
            try:
                return await node(state, config)
            except GraphBubbleUp:
                raise
            except Exception:
                # A storage/schema/transport exception must never leak its raw
                # payload through host exception logs or bypass the write gate.
                messages = []
                last = state["messages"][-1]
                if isinstance(last, AIMessage):
                    messages = [ToolMessage(content="Execution blocked.", tool_call_id=c["id"], name=c["name"], status="error") for c in last.tool_calls]
                return {"messages": [*messages, _notice("execution_blocked", "Validation or storage unavailable. No further call; check any uncertain operation.")],
                        "approval_stop": True}
        return guarded

    workflow = StateGraph(NotionChatState)
    workflow.add_node("turn", safe_execution_node(enter_turn))
    workflow.add_node("model", call_model)
    workflow.add_node("tools", safe_execution_node(call_tools))
    workflow.add_node("ssh", safe_execution_node(run_ssh))
    workflow.set_entry_point("turn")
    workflow.add_conditional_edges("turn", lambda state: END if state.get("approval_stop") else "model")
    workflow.add_conditional_edges("model", route_model)
    workflow.add_conditional_edges("tools", lambda state: END if state["messages"][-1].type == "ai" else "model")
    workflow.add_conditional_edges("ssh", lambda state: END if state["messages"][-1].type == "ai" else "model")
    return workflow.compile(checkpointer=checkpointer)


def _error_code(error):
    """The JSON-RPC code of an MCP error, wherever the client library keeps it."""
    for candidate in (error, getattr(error, "error", None)):
        code = getattr(candidate, "code", None)
        if isinstance(code, int):
            return code
    return None


def _redacted(error) -> str:
    """A short, URL-free hint of what the toolbox answered: links may carry sign-in data."""
    text = re.sub(r"https?://\S+", "<url>", str(error))
    return re.sub(r"[A-Za-z0-9_\-]{40,}", "<redacted>", text)[:160]


def _consent_text(url):
    if not url.startswith("https://mcp.notion.com/authorize?"):
        return url
    return f"[Connect Notion]({url})\n\nAfter you consent, come back to this conversation and write “connected”. I will resume your request."


def _tool_error(error: Exception) -> str:
    if isinstance(error, GraphBubbleUp):
        raise error
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return json.dumps({"code": "tool_timeout", "message": "The tool did not answer in time.", "retryable": True},
                          ensure_ascii=False)
    transient = reliability.is_transient(error)
    body = {"code": "tool_temporarily_unavailable" if transient else "tool_execution_failed",
            "message": ("The service is temporarily unavailable." if transient
                        else "The call failed. Check the result before retrying a write."),
            "retryable": transient}
    if transient:
        wait = reliability.retry_after_seconds(error)
        if wait:
            body["retry_after"] = wait
    return json.dumps(body, ensure_ascii=False)
