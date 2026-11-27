"""Intake against a real Postgres: exactly-once storage, encryption at rest, masked audit, duplicate hints."""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from app.db.migrations import connect
from app.enrollments.intake import DuplicateInFlight, Intake, derived_key
from app.enrollments.store import EnrollmentStore
from app.security.crypto import FieldCipher, Fingerprinter, new_key
from app.shared.store import MemoryStore, RedisStore, SharedStore
from tests.conftest import TEST_DB, academy_adult, club_adult, needs_db

pytestmark = needs_db
TEST_REDIS = os.environ.get("TEST_REDIS_URL", "")


async def _with_intake(body: Callable[[Intake, Any], Awaitable[None]], shared: SharedStore | None = None) -> None:
    import asyncpg
    conn = await asyncpg.connect(TEST_DB)
    await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    await conn.close()
    pool = await connect(TEST_DB)
    try:
        store = EnrollmentStore(pool, FieldCipher([new_key()]))
        await body(Intake(store, shared or MemoryStore(), Fingerprinter(new_key()), ttl_s=600), pool)
    finally:
        await pool.close()


def run(body: Callable[[Intake, Any], Awaitable[None]], shared: SharedStore | None = None) -> None:
    asyncio.run(_with_intake(body, shared))


def test_same_key_twice_is_one_enrollment() -> None:
    async def body(intake: Intake, pool: Any) -> None:
        first = await intake.receive(target_form="riverside-enrollment", source="webhook", record=academy_adult(),
                                     idempotency_key="crm-123", actor="t")
        again = await intake.receive(target_form="riverside-enrollment", source="webhook", record=academy_adult(),
                                     idempotency_key="crm-123", actor="t")
        assert first.created and not again.created
        assert again.enrollment.enrollment_id == first.enrollment.enrollment_id
        assert await pool.fetchval("SELECT count(*) FROM enrollments") == 1
    run(body)


def test_database_gate_holds_when_shared_state_is_lost() -> None:
    async def body(intake: Intake, pool: Any) -> None:
        first = await intake.receive(target_form="riverside-enrollment", source="api", record=academy_adult(),
                                     idempotency_key="k-1", actor="t")
        intake.shared = MemoryStore()  # Redis flushed or restarted
        again = await intake.receive(target_form="riverside-enrollment", source="api", record=academy_adult(),
                                     idempotency_key="k-1", actor="t")
        assert not again.created and again.enrollment.enrollment_id == first.enrollment.enrollment_id
        assert await pool.fetchval("SELECT count(*) FROM enrollments") == 1
    run(body)


def test_derived_key_recognises_the_same_record_and_not_a_changed_one() -> None:
    async def body(intake: Intake, pool: Any) -> None:
        a = await intake.receive(target_form="harbour-membership", source="csv", record=club_adult(),
                                 idempotency_key=None, actor="t")
        # Same content, different key order: still the same record.
        b = await intake.receive(target_form="harbour-membership", source="csv",
                                 record=dict(reversed(list(club_adult().items()))), idempotency_key=None, actor="t")
        c = await intake.receive(target_form="harbour-membership", source="csv",
                                 record=club_adult(membership_type="off_peak"), idempotency_key=None, actor="t")
        assert a.created and not b.created and c.created
        assert a.enrollment.idempotency_key.startswith("auto:")
        assert a.enrollment.enrollment_id == b.enrollment.enrollment_id != c.enrollment.enrollment_id
        # The changed record is the same applicant: flagged for a reviewer, not silently merged.
        assert c.possible_duplicates == [a.enrollment.enrollment_id]
    run(body)


def test_derived_key_depends_on_the_form() -> None:
    fp = Fingerprinter(new_key())
    rec = {"email": "x@example.com"}
    assert derived_key(fp, "riverside-enrollment", rec) != derived_key(fp, "harbour-membership", rec)


def test_concurrent_replays_store_one_row() -> None:
    async def body(intake: Intake, pool: Any) -> None:
        async def send() -> str:
            try:
                r = await intake.receive(target_form="riverside-enrollment", source="webhook",
                                         record=academy_adult(), idempotency_key="burst-1", actor="t")
                return "created" if r.created else "replay"
            except DuplicateInFlight:
                return "in_flight"
        results = await asyncio.gather(*(send() for _ in range(12)))
        assert results.count("created") == 1
        assert set(results) <= {"created", "replay", "in_flight"}
        assert await pool.fetchval("SELECT count(*) FROM enrollments") == 1
    run(body)


def test_concurrent_inserts_without_any_shared_gate_still_store_one_row() -> None:
    async def body(intake: Intake, pool: Any) -> None:
        results = await asyncio.gather(*(intake.store.create(
            idempotency_key="race-1", source="api", target_form="riverside-enrollment", record=academy_adult(),
            applicant_fp=None, actor="t") for _ in range(8)))
        assert sum(created for _, created in results) == 1
        assert len({e.enrollment_id for e, _ in results}) == 1
    run(body)


def test_personal_data_is_encrypted_at_rest() -> None:
    async def body(intake: Intake, pool: Any) -> None:
        r = await intake.receive(target_form="riverside-enrollment", source="json", record=academy_adult(),
                                 idempotency_key="enc-1", actor="t")
        raw = await pool.fetchrow("SELECT * FROM enrollments")
        blob = bytes(raw["source_record"])
        for secret in (b"amara", b"Okafor", b"07911", b"1998-05-14", b"Mill Lane"):
            assert secret.lower() not in blob.lower()
        assert raw["applicant_fp"] and "amara" not in raw["applicant_fp"]
        assert r.enrollment.source_record == academy_adult()  # and it opens again for the engine
    run(body)


def test_a_row_cannot_be_moved_to_another_record() -> None:
    async def body(intake: Intake, pool: Any) -> None:
        for key in ("a", "b"):
            await intake.receive(target_form="riverside-enrollment", source="api",
                                 record=academy_adult(first_name=key.upper() + "nna"), idempotency_key=key, actor="t")
        rows = await pool.fetch("SELECT id, source_record FROM enrollments ORDER BY created_at")
        # Swap the sealed payloads: the record id is authenticated data, so neither opens.
        await pool.execute("UPDATE enrollments SET source_record = $2 WHERE id = $1", rows[0]["id"],
                           rows[1]["source_record"])
        from app.security.crypto import CryptoError
        first = await pool.fetchval("SELECT enrollment_id FROM enrollments WHERE id = $1", rows[0]["id"])
        with pytest.raises(CryptoError):
            await intake.store.get(first)
    run(body)


def test_audit_log_never_holds_personal_values() -> None:
    async def body(intake: Intake, pool: Any) -> None:
        r = await intake.receive(target_form="riverside-enrollment", source="notes", record=academy_adult(),
                                 idempotency_key="aud-1", actor="ops@school")
        await intake.store.audit(r.enrollment, "t", "note", {"email": "amara.okafor@example.com",
                                                             "comment": "call 07911 123456 on 14/05/1998"})
        dump = json.dumps([dict(x) for x in await pool.fetch("SELECT actor, action, details FROM audit_logs")],
                          default=str)
        for secret in ("amara", "07911", "1998", "Mill Lane"):
            assert secret.lower() not in dump.lower()
        trail = await intake.store.audit_trail(r.enrollment)
        assert trail[0]["action"] == "enrollment.received"
        assert "email" in trail[0]["details"]["fields"]  # field names are kept: they say what arrived
    run(body)


def test_unknown_form_stores_nothing() -> None:
    async def body(intake: Intake, pool: Any) -> None:
        with pytest.raises(KeyError):
            await intake.receive(target_form="nope", source="api", record={"a": 1}, idempotency_key="x", actor="t")
        assert await pool.fetchval("SELECT count(*) FROM enrollments") == 0
    run(body)


@pytest.mark.skipif(not TEST_REDIS, reason="set TEST_REDIS_URL to run against a real Redis")
def test_redis_gate() -> None:
    from redis.asyncio import Redis

    async def body(intake: Intake, pool: Any) -> None:
        await intake.shared.client.flushdb()  # type: ignore[attr-defined]
        first = await intake.receive(target_form="riverside-enrollment", source="api", record=academy_adult(),
                                     idempotency_key="r-1", actor="t")
        assert await intake.shared.get("idem:r-1") == first.enrollment.enrollment_id
        again = await intake.receive(target_form="riverside-enrollment", source="api", record=academy_adult(),
                                     idempotency_key="r-1", actor="t")
        assert not again.created
    run(body, RedisStore(Redis.from_url(TEST_REDIS, decode_responses=True)))
