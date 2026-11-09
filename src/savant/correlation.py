"""Correlation id shared by the BFF and the agent logs (task 30).

Both sides know the Foundry response id of a turn: the agent receives it as the turn id, the BFF
reads it from the stream's final event. Logging a short hash of it instead of the raw id keeps
identifiers out of the logs while letting one KQL query join both sides.
"""

from __future__ import annotations

import hashlib
import re

_CORRELATION = re.compile(r"[0-9a-f]{16}")


def correlation_id(response_id: object) -> str:
    """16 hex characters derived from a response id, or "-" when there is none."""
    if not isinstance(response_id, str) or not response_id:
        return "-"
    return hashlib.sha256(response_id.encode()).hexdigest()[:16]


def is_correlation_id(value: object) -> bool:
    return isinstance(value, str) and _CORRELATION.fullmatch(value) is not None
