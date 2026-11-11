"""Encrypted, transactional, single-use authorization for external mutations.

Claim before network I/O. A claimed action is never automatically reclaimable:
process death or an uncertain response requires inspecting the remote result.
The provided OAuth store supplies durable encryption and cross-process locking.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from uuid import uuid4


def operation_digest(operation: dict) -> str:
    """Fingerprint the exact tool, arguments and schema shown for approval."""
    return hashlib.sha256(
        json.dumps(operation, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def _key(*parts: str) -> str:
    if any(not isinstance(part, str) or not part.strip() for part in parts):
        raise ValueError("Authorization requires a nonempty owner, thread and identifier.")
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


class ApprovalLedger:
    def __init__(self, store, *, clock=time.time, ttl: int = 900):
        if not 0 < ttl <= 900:
            raise ValueError("Approval lifetime must be between 1 and 900 seconds.")
        self.store, self.clock, self.ttl = store, clock, ttl

    async def bind_thread(self, owner: str, thread: str) -> bool:
        """Permanently bind a conversation to its first trusted owner."""
        thread_key, owner_key = _key(thread), _key(owner)
        async with self.store.transaction() as data:
            bindings = data.setdefault("approval_thread_owners", {})
            if thread_key in bindings:
                return bindings[thread_key] == owner_key
            bindings[thread_key] = owner_key
            return True

    async def claim_automatic(self, owner: str, thread: str, action_id: str, digest: str) -> bool:
        """Claim an allowed automatic write before I/O, without creating an approval prompt."""
        scope = _key(owner, thread)
        _key(action_id)
        if not await self.bind_thread(owner, thread):
            return False
        async with self.store.transaction() as data:
            actions = data.setdefault("automatic_actions", {}).setdefault(scope, {})
            if action_id in actions:
                return False
            actions[action_id] = {"digest": digest, "status": "claimed", "claimed_at": self.clock()}
            return True

    async def finish_automatic(self, owner: str, thread: str, action_id: str, status: str) -> bool:
        if status not in {"succeeded", "failed", "unknown"}:
            raise ValueError("Invalid terminal action status.")
        async with self.store.transaction() as data:
            record = data.get("automatic_actions", {}).get(_key(owner, thread), {}).get(action_id)
            if not record or record["status"] != "claimed":
                return False
            record["status"] = status
            record["finished_at"] = self.clock()
            return True

    async def create(self, owner: str, thread: str, operation: dict, action_id: str | None = None) -> dict:
        scope = _key(owner, thread)
        action_id = action_id or str(uuid4())
        _key(action_id)
        digest = operation_digest(operation)
        if not await self.bind_thread(owner, thread):
            raise ValueError("Conversation belongs to another owner.")
        async with self.store.transaction() as data:
            actions = data.setdefault("approval_actions", {}).setdefault(scope, {})
            existing = actions.get(action_id)
            if existing:
                if existing["digest"] != digest:
                    raise ValueError("Action identifier already belongs to a different operation.")
                return copy.deepcopy(existing)
            now = self.clock()
            record = dict(
                action_id=action_id,
                digest=digest,
                operation=copy.deepcopy(operation),
                status="pending",
                created_at=now,
                expires_at=now + self.ttl,
            )
            actions[action_id] = record
            return copy.deepcopy(record)

    async def get(self, owner: str, thread: str, action_id: str) -> dict | None:
        scope = _key(owner, thread)
        async with self.store.transaction() as data:
            record = data.get("approval_actions", {}).get(scope, {}).get(action_id)
            if record and record["status"] == "pending" and record["expires_at"] <= self.clock():
                record["status"] = "expired"
            return copy.deepcopy(record)

    async def presentation(self, owner: str, thread: str) -> dict | None:
        scope = _key(owner, thread)
        async with self.store.transaction() as data:
            return copy.deepcopy(data.get("approval_presentations", {}).get(scope))

    async def present(self, owner: str, thread: str, action_id: str, response_id: str) -> bool:
        """Record the one canonical operation actually offered for consent.

        Independent concurrent proposals cannot replace the first pending action.
        This binding survives stale checkpoints and conversation-only transports.
        """
        scope = _key(owner, thread)
        _key(response_id)
        async with self.store.transaction() as data:
            actions = data.get("approval_actions", {}).get(scope, {})
            active = []
            for record in actions.values():
                if record["status"] == "pending" and record["expires_at"] <= self.clock():
                    record["status"] = "expired"
                if record["status"] == "pending":
                    active.append(record["action_id"])
            if not active or active[0] != action_id:
                return False
            data.setdefault("approval_presentations", {})[scope] = {"action_id": action_id, "response_id": response_id}
            return True

    async def claim(
        self,
        owner: str,
        thread: str,
        action_id: str,
        digest: str,
        *,
        message_id: str,
        presentation_id: str | None = None,
    ) -> bool:
        scope, message_key = _key(owner, thread), _key(owner, thread, message_id)
        async with self.store.transaction() as data:
            record = data.get("approval_actions", {}).get(scope, {}).get(action_id)
            used = data.setdefault("approval_consumed_messages", {})
            if presentation_id is not None:
                presented = data.get("approval_presentations", {}).get(scope, {})
                if presented.get("action_id") != action_id or presented.get("response_id") != presentation_id:
                    return False
            if not record or record["status"] != "pending" or record["digest"] != digest:
                return False
            if record["expires_at"] <= self.clock():
                record["status"] = "expired"
                return False
            if message_key in used:
                return False
            used[message_key] = action_id
            record["status"] = "claimed"
            record["claimed_at"] = self.clock()
            return True

    async def finish(self, owner: str, thread: str, action_id: str, status: str) -> bool:
        if status not in {"succeeded", "failed", "unknown"}:
            raise ValueError("Invalid terminal action status.")
        scope = _key(owner, thread)
        async with self.store.transaction() as data:
            record = data.get("approval_actions", {}).get(scope, {}).get(action_id)
            if not record or record["status"] != "claimed":
                return False
            record["status"] = status
            record["finished_at"] = self.clock()
            return True

    async def reject(self, owner: str, thread: str, action_id: str) -> bool:
        scope = _key(owner, thread)
        async with self.store.transaction() as data:
            record = data.get("approval_actions", {}).get(scope, {}).get(action_id)
            if not record or record["status"] != "pending":
                return False
            record["status"] = "rejected"
            return True
