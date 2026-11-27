"""Keeping stored personal data in order: re-encrypting under the newest key, and erasing it when no longer needed."""
from __future__ import annotations

import json
from typing import Any

import asyncpg

from app.security.crypto import FieldCipher

DONE = ("submitted", "rejected")


async def rotate(pool: asyncpg.Pool, cipher: FieldCipher) -> dict[str, int]:
    """Re-seal everything not yet under the first key in ENCRYPTION_KEYS. Safe to run repeatedly and to stop:
    each row is re-sealed in its own transaction. Old keys can be removed once this reports zeros."""
    counts = {"enrollments": 0, "field_mappings": 0, "screenshots": 0}
    for row in await pool.fetch("SELECT id, source_record, mapped_payload FROM enrollments"):
        rid = str(row["id"])
        updates: dict[str, bytes] = {}
        for col in ("source_record", "mapped_payload"):
            blob = row[col]
            if blob is not None and cipher.needs_rotation(blob):
                updates[col] = cipher.seal(cipher.open(blob, rid), rid)
        if updates:
            sets = ", ".join(f"{c} = ${i + 2}" for i, c in enumerate(updates))
            await pool.execute(f"UPDATE enrollments SET {sets} WHERE id = $1", row["id"], *updates.values())  # noqa: S608
            counts["enrollments"] += 1
    for row in await pool.fetch("SELECT id, enrollment_id, field, value, assumption FROM field_mappings"):
        ad = f"{row['enrollment_id']}:{row['field']}"
        new: dict[str, Any] = {}
        for col in ("value", "assumption"):
            blob = row[col]
            if blob is not None and cipher.needs_rotation(blob):
                new[col] = cipher.seal(cipher.open(blob, ad), ad)
        if new:
            await pool.execute("UPDATE field_mappings SET value = COALESCE($2, value), "
                               "assumption = COALESCE($3, assumption) WHERE id = $1",
                               row["id"], new.get("value"), new.get("assumption"))
            counts["field_mappings"] += 1
    for row in await pool.fetch("SELECT id, run_id, seq, content FROM run_artifacts"):
        if cipher.needs_rotation(row["content"]):
            ad = f"{row['run_id']}:{row['seq']}"
            await pool.execute("UPDATE run_artifacts SET content = $2 WHERE id = $1", row["id"],
                               cipher.seal_bytes(cipher.open_bytes(row["content"], ad), ad))
            counts["screenshots"] += 1
    return counts


async def purge(pool: asyncpg.Pool, cipher: FieldCipher, older_than_days: int) -> list[str]:
    """Erase the personal data of finished enrollments (submitted or rejected) not touched for `older_than_days`.
    What stays: the enrollment ID, status, outcome, reasons (which never hold values), portal reference, run
    records without screenshots, and the audit trail, which records the purge."""
    rows = await pool.fetch(
        "SELECT id, enrollment_id FROM enrollments WHERE status = ANY($1::text[]) "
        "AND updated_at < now() - make_interval(days => $2) AND mapping_meta->>'purged' IS NULL",
        list(DONE), older_than_days)
    done = []
    for r in rows:
        rid = str(r["id"])
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "UPDATE enrollments SET source_record = $2, mapped_payload = NULL, applicant_fp = NULL, "
                "mapping_meta = mapping_meta || '{\"purged\": true}'::jsonb WHERE id = $1",
                r["id"], cipher.seal({}, rid))
            await conn.execute("UPDATE field_mappings SET value = NULL, assumption = NULL WHERE enrollment_id = $1",
                               r["id"])
            await conn.execute("DELETE FROM run_artifacts WHERE run_id IN (SELECT id FROM submission_runs "
                               "WHERE enrollment_id = $1)", r["id"])
            await conn.execute("INSERT INTO audit_logs (enrollment_id, actor, action, details) VALUES ($1, $2, $3, $4)",
                               r["id"], "retention", "personal_data.purged",
                               json.dumps({"after_days": older_than_days}))
        done.append(r["enrollment_id"])
    return done
