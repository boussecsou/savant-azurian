"""One rule for every tool call: bounded time, bounded retries, readable failures.

- Each tool call has a timeout. A read that fails for a transient reason (timeout, network,
  HTTP 429/502/503/504) is retried once after a short pause; a write is never retried
  automatically, its outcome is reported as uncertain instead.
- A turn cannot loop on tools: after MAX_TOOL_ROUNDS model steps that asked for tools, the agent
  stops and says so.
- Sensitive operations keep their own confirmation paths (Notion and toolbox: semantic approval
  and one-shot ledger; SSH: later-turn confirmation); this module never bypasses them.
"""

from __future__ import annotations

import asyncio
import json
import random

import httpx
from jsonschema import exceptions as schema_exceptions
from jsonschema import validators

TOOL_TIMEOUT_SECONDS = 60.0
LOADER_TIMEOUT_SECONDS = 30.0
# The toolbox lists in ~7 s when warm: waiting 30 s for it on every turn made a down toolbox cost 30 s each time.
TOOLBOX_TIMEOUT_SECONDS = 12.0
# After a failed toolbox load, do not try again for this long: the turns in between answer at once without it.
TOOLBOX_COOLDOWN_SECONDS = 45.0
READ_RETRIES = 1
RETRY_DELAY_SECONDS = 1.0
RETRY_MAX_DELAY_SECONDS = 8.0
MAX_TOOL_ROUNDS = 8
# Reads that are independent run side by side, but never more than this many at once.
MAX_PARALLEL_READS = 4
# A tool result longer than this is cut: one huge page must not fill the context for the rest of the thread.
MAX_TOOL_RESULT_CHARS = 20_000
# The model sees full tool results for the latest turns only; older ones are replaced by a short marker.
HISTORY_KEEP_TURNS = 3
HISTORY_KEEP_CHARS = 500

_TRANSIENT_STATUS = frozenset({408, 429, 502, 503, 504})


def is_transient(error: BaseException) -> bool:
    """True when trying the same read again may succeed."""
    if isinstance(error, (asyncio.TimeoutError, TimeoutError, ConnectionError, httpx.TransportError)):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in _TRANSIENT_STATUS
    status = getattr(getattr(error, "response", None), "status_code", None)
    return isinstance(status, int) and status in _TRANSIENT_STATUS


def is_retryable_result(content) -> bool:
    """A tool message produced by the shared error handler that marked the failure transient."""
    if not isinstance(content, str):
        return False
    try:
        body = json.loads(content)
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("retryable") is True


def tool_rounds_this_turn(messages) -> int:
    """How many model steps asked for tools since the latest user message."""
    latest_human = max((i for i, m in enumerate(messages) if m.type == "human"), default=-1)
    return sum(1 for m in messages[latest_human + 1 :] if m.type == "ai" and getattr(m, "tool_calls", None))


def retry_delay(attempt: int, retry_after: float | None = None, rng=random.random) -> float:
    """Exponential backoff with jitter (so retries do not line up), never shorter than a server's Retry-After."""
    base = RETRY_DELAY_SECONDS * (2**attempt)
    delay = min(base + base * 0.25 * rng(), RETRY_MAX_DELAY_SECONDS)
    if retry_after is not None and retry_after > 0:
        delay = min(max(delay, retry_after), RETRY_MAX_DELAY_SECONDS)
    return delay


def retry_after_seconds(error: BaseException) -> float | None:
    """Seconds a server asked us to wait (Retry-After as a number), if the error carries them."""
    headers = getattr(getattr(error, "response", None), "headers", None)
    try:
        value = float(headers.get("retry-after")) if headers is not None else None
    except (TypeError, ValueError):
        return None
    return value if value is not None and value > 0 else None


def retry_after_of(content) -> float | None:
    """The `retry_after` the shared error handler put in a tool message, if any."""
    try:
        body = json.loads(content) if isinstance(content, str) else None
    except ValueError:
        return None
    value = body.get("retry_after") if isinstance(body, dict) else None
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


def schema_problem(tool, args) -> str | None:
    """Why `args` cannot match the tool's JSON schema, worded so the model can fix its call; None if fine.

    Checked before the call: a wrong argument is answered at once and precisely instead of after a round
    trip to the service. A schema that cannot be read, or is not a plain JSON schema, never blocks a call.
    """
    schema = getattr(tool, "args_schema", None)
    if not isinstance(schema, dict) or not isinstance(args, dict):
        return None
    try:
        validator = validators.validator_for(schema)(schema)
        error = next(iter(sorted(validator.iter_errors(args), key=lambda e: list(map(str, e.path)))), None)
    except (schema_exceptions.SchemaError, Exception):
        return None
    if error is None:
        return None
    where = ".".join(str(part) for part in error.path) or "arguments"
    return f"{where}: {error.message}"[:240]


def _clip_text(text: str) -> str:
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    more = len(text) - MAX_TOOL_RESULT_CHARS
    return (
        text[:MAX_TOOL_RESULT_CHARS] + f"\n[Truncated: {more} more characters. "
        "Ask for a narrower part: a section, a smaller limit or the next page.]"
    )


def cap_result(message):
    """A tool message whose text is at most MAX_TOOL_RESULT_CHARS long (a list of blocks shares that budget)."""
    content = message.content
    if isinstance(content, str):
        clipped = _clip_text(content)
    elif isinstance(content, list):
        budget, clipped = MAX_TOOL_RESULT_CHARS, []
        for block in content:
            text = block.get("text") if isinstance(block, dict) else block if isinstance(block, str) else None
            if text is None:
                clipped.append(block)
                continue
            piece = text if len(text) <= budget else text[: max(budget, 0)] + "\n[Truncated: ask for a narrower part.]"
            budget -= len(text)
            clipped.append({**block, "text": piece} if isinstance(block, dict) else piece)
    else:
        return message
    return message if clipped == content else message.model_copy(update={"content": clipped})


def compact_history(messages, keep_turns: int = HISTORY_KEEP_TURNS):
    """The messages the model should see: tool results of older turns shrunk to a marker.

    Only the copy sent to the model changes; the saved conversation keeps everything. Roles, ids and the
    owner's and the agent's own words are untouched, so the thread still makes sense and the agent can
    read the data again if it needs to.
    """
    humans = [i for i, m in enumerate(messages) if m.type == "human"]
    if len(humans) <= keep_turns:
        return messages
    cutoff = humans[-keep_turns]
    compacted = []
    for index, message in enumerate(messages):
        long_result = (
            index < cutoff
            and message.type == "tool"
            and len(message.content if isinstance(message.content, str) else json.dumps(message.content, default=str))
            > HISTORY_KEEP_CHARS
        )
        compacted.append(
            message.model_copy(update={"content": "[Result of an earlier step, left out to save space.]"})
            if long_result
            else message
        )
    return compacted
