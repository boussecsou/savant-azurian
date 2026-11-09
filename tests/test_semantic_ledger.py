"""Real encrypted SQLite transactions validate restart and single-use claims."""
import asyncio

from cryptography.fernet import Fernet
import pytest

from savant.notion_oauth import SQLiteOAuthStore
from savant.semantic_ledger import ApprovalLedger, operation_digest


OPERATION = {"tool_name": "notion-update-page", "args": {"page_id": "page", "title": "New"},
             "schema_fingerprint": "schema-v1"}


def test_restart_concurrency_and_single_use(tmp_path):
    async def scenario():
        path, key = str(tmp_path / "oauth.sqlite"), Fernet.generate_key().decode()
        first = ApprovalLedger(SQLiteOAuthStore(path, key))
        action = await first.create("owner", "thread", OPERATION)
        restarted = ApprovalLedger(SQLiteOAuthStore(path, key))
        assert (await restarted.get("owner", "thread", action["action_id"])) == action
        claims = await asyncio.gather(*[
            ledger.claim("owner", "thread", action["action_id"], action["digest"], message_id="yes-1")
            for ledger in (first, restarted)
        ])
        assert sorted(claims) == [False, True]
        assert await restarted.finish("owner", "thread", action["action_id"], "unknown")
        assert not await first.claim("owner", "thread", action["action_id"], action["digest"], message_id="yes-2")
        assert not await first.finish("owner", "thread", action["action_id"], "succeeded")
        second = await first.create("owner", "thread", OPERATION)
        assert not await restarted.claim("owner", "thread", second["action_id"], second["digest"], message_id="yes-1")
        assert await restarted.claim("owner", "thread", second["action_id"], second["digest"], message_id="yes-2")
    asyncio.run(scenario())


def test_scope_expiry_rejection_and_parameter_binding(tmp_path):
    async def scenario():
        now = [1000]
        ledger = ApprovalLedger(SQLiteOAuthStore(str(tmp_path / "oauth.sqlite"), Fernet.generate_key().decode()),
                                clock=lambda: now[0], ttl=30)
        action = await ledger.create("owner", "thread", OPERATION, "action")
        assert await ledger.bind_thread("owner", "thread")
        assert not await ledger.bind_thread("other", "thread")
        assert await ledger.get("other", "thread", "action") is None
        assert await ledger.get("owner", "other", "action") is None
        assert not await ledger.claim("owner", "thread", "action", "tampered", message_id="yes")
        with pytest.raises(ValueError):
            await ledger.create("owner", "thread", {**OPERATION, "args": {}}, "action")
        with pytest.raises(ValueError):
            await ledger.create("other", "thread", OPERATION)
        now[0] += 30
        assert not await ledger.claim("owner", "thread", "action", action["digest"], message_id="yes")
        assert (await ledger.get("owner", "thread", "action"))["status"] == "expired"
        assert (await ledger.create("owner", "thread", OPERATION, "action"))["status"] == "expired"
        declined = await ledger.create("owner", "thread", OPERATION)
        assert await ledger.reject("owner", "thread", declined["action_id"])
        assert not await ledger.claim("owner", "thread", declined["action_id"], declined["digest"], message_id="no")
    asyncio.run(scenario())


def test_canonical_digest_and_detached_records(tmp_path):
    assert operation_digest({"a": 1, "b": 2}) == operation_digest({"b": 2, "a": 1})
    with pytest.raises(ValueError):
        operation_digest({"value": float("nan")})
    async def scenario():
        ledger = ApprovalLedger(SQLiteOAuthStore(str(tmp_path / "oauth.sqlite"), Fernet.generate_key().decode()))
        action = await ledger.create("owner", "thread", OPERATION)
        action["operation"]["args"]["title"] = "Tampered"
        stored = await ledger.get("owner", "thread", action["action_id"])
        assert stored["operation"]["args"]["title"] == "New"
        assert await ledger.claim("owner", "thread", action["action_id"], stored["digest"], message_id="yes")
        assert await ledger.finish("owner", "thread", action["action_id"], "succeeded")
        assert not await ledger.reject("owner", "thread", action["action_id"])
    asyncio.run(scenario())


def test_presentation_is_durable_and_serializes_pending_operations(tmp_path):
    async def scenario():
        path, key = str(tmp_path / "oauth.sqlite"), Fernet.generate_key().decode()
        first = ApprovalLedger(SQLiteOAuthStore(path, key))
        one = await first.create("owner", "thread", OPERATION, "action-one")
        two = await first.create("owner", "thread", {**OPERATION, "args": {"page_id": "two"}}, "action-two")

        assert await first.present("owner", "thread", one["action_id"], "response-one")
        restarted = ApprovalLedger(SQLiteOAuthStore(path, key))
        assert await restarted.presentation("owner", "thread") == {
            "action_id": one["action_id"], "response_id": "response-one"}
        assert not await restarted.present("owner", "thread", two["action_id"], "response-two")

        assert await restarted.claim("owner", "thread", one["action_id"], one["digest"],
                                     message_id="approval-one", presentation_id="response-one")
        assert await restarted.finish("owner", "thread", one["action_id"], "succeeded")
        assert await restarted.present("owner", "thread", two["action_id"], "response-two")
    asyncio.run(scenario())


def test_stale_presentation_fails_atomically_without_consuming_confirmation(tmp_path):
    async def scenario():
        ledger = ApprovalLedger(SQLiteOAuthStore(str(tmp_path / "oauth.sqlite"), Fernet.generate_key().decode()))
        action = await ledger.create("owner", "thread", OPERATION, "action")
        assert await ledger.present("owner", "thread", action["action_id"], "response-old")
        assert await ledger.present("owner", "thread", action["action_id"], "response-current")

        assert not await ledger.claim("owner", "thread", action["action_id"], action["digest"],
                                      message_id="same-message", presentation_id="response-old")
        assert await ledger.claim("owner", "thread", action["action_id"], action["digest"],
                                  message_id="same-message", presentation_id="response-current")
    asyncio.run(scenario())


def test_confirmation_message_can_claim_at_most_one_pending_action_concurrently(tmp_path):
    async def scenario():
        ledger = ApprovalLedger(SQLiteOAuthStore(str(tmp_path / "oauth.sqlite"), Fernet.generate_key().decode()))
        one = await ledger.create("owner", "thread", OPERATION, "action-one")
        two = await ledger.create("owner", "thread", {**OPERATION, "args": {"page_id": "two"}}, "action-two")
        claims = await asyncio.gather(
            ledger.claim("owner", "thread", one["action_id"], one["digest"], message_id="one-yes"),
            ledger.claim("owner", "thread", two["action_id"], two["digest"], message_id="one-yes"),
        )
        assert sorted(claims) == [False, True]
    asyncio.run(scenario())
