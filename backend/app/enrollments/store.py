"""Enrollment records in Postgres. Personal data is sealed with the record's own id before it is written;
callers pass and receive plain Python values."""
from __future__ import annotations

import json
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import asyncpg

from app.mapping.result import FieldResult
from app.security.crypto import FieldCipher
from app.security.masking import mask_value

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O/1/I: read aloud and typed without mistakes


def new_enrollment_id() -> str:
    return "ENR-" + "".join(secrets.choice(_ALPHABET) for _ in range(8))


@dataclass
class Enrollment:
    id: uuid.UUID
    enrollment_id: str
    idempotency_key: str
    source: str
    target_form: str
    status: str
    outcome: str | None
    issues: list[dict[str, Any]]
    source_record: dict[str, Any]
    mapped_payload: dict[str, Any] | None
    submit_path: str | None
    confirmation_ref: str | None
    created_at: datetime
    updated_at: datetime
    applicant_fp: str | None = None
    mapper: str | None = None
    min_confidence: float | None = None
    mapping_meta: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        """What may be shown without revealing personal data."""
        return {"enrollment_id": self.enrollment_id, "target_form": self.target_form, "source": self.source,
                "status": self.status, "outcome": self.outcome, "reasons": self.issues,
                "submit_path": self.submit_path, "confirmation_ref": self.confirmation_ref,
                "mapper": self.mapper, "min_confidence": self.min_confidence,
                "created_at": self.created_at.isoformat(), "updated_at": self.updated_at.isoformat()}


class EnrollmentStore:
    def __init__(self, pool: asyncpg.Pool, cipher: FieldCipher):
        self.pool = pool
        self.cipher = cipher

    def _row(self, r: asyncpg.Record) -> Enrollment:
        rid = str(r["id"])
        mapped = self.cipher.open(r["mapped_payload"], rid) if r["mapped_payload"] is not None else None
        return Enrollment(id=r["id"], enrollment_id=r["enrollment_id"], idempotency_key=r["idempotency_key"],
                          source=r["source"], target_form=r["target_form"], status=r["status"], outcome=r["outcome"],
                          issues=json.loads(r["issues"]), source_record=self.cipher.open(r["source_record"], rid),
                          mapped_payload=mapped, submit_path=r["submit_path"],
                          confirmation_ref=r["confirmation_ref"], created_at=r["created_at"],
                          updated_at=r["updated_at"], applicant_fp=r["applicant_fp"], mapper=r["mapper"],
                          min_confidence=r["min_confidence"], mapping_meta=json.loads(r["mapping_meta"]))

    async def create(self, *, idempotency_key: str, source: str, target_form: str, record: dict[str, Any],
                     applicant_fp: str | None, actor: str) -> tuple[Enrollment, bool]:
        """Insert once per idempotency key. Returns (enrollment, created); a replay returns the first one."""
        rid = uuid.uuid4()
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """INSERT INTO enrollments (id, enrollment_id, idempotency_key, source, target_form, source_record,
                                            applicant_fp)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)
                   ON CONFLICT (idempotency_key) DO NOTHING
                   RETURNING *""",
                rid, new_enrollment_id(), idempotency_key, source, target_form,
                self.cipher.seal(record, str(rid)), applicant_fp)
            if row is None:
                existing = await conn.fetchrow("SELECT * FROM enrollments WHERE idempotency_key = $1",
                                               idempotency_key)
                assert existing is not None
                return self._row(existing), False
            await self._audit(conn, row["id"], actor, "enrollment.received",
                              {"source": source, "target_form": target_form, "fields": sorted(record)})
            return self._row(row), True

    async def get(self, enrollment_id: str) -> Enrollment | None:
        row = await self.pool.fetchrow("SELECT * FROM enrollments WHERE enrollment_id = $1", enrollment_id)
        return self._row(row) if row else None

    async def get_by_key(self, idempotency_key: str) -> Enrollment | None:
        row = await self.pool.fetchrow("SELECT * FROM enrollments WHERE idempotency_key = $1", idempotency_key)
        return self._row(row) if row else None

    async def same_applicant(self, target_form: str, applicant_fp: str, exclude: uuid.UUID) -> list[str]:
        """Other enrollments for the same form and the same email: possible duplicates for a reviewer."""
        rows = await self.pool.fetch(
            "SELECT enrollment_id FROM enrollments WHERE target_form = $1 AND applicant_fp = $2 AND id <> $3 "
            "AND status <> 'rejected' ORDER BY created_at", target_form, applicant_fp, exclude)
        return [r["enrollment_id"] for r in rows]

    async def list_recent(self, limit: int = 50, status: str | None = None, *, outcome: str | None = None,
                          form: str | None = None, q: str | None = None, offset: int = 0) -> list[Enrollment]:
        rows = await self.pool.fetch(
            """SELECT * FROM enrollments
               WHERE ($1::text IS NULL OR status = $1) AND ($2::text IS NULL OR outcome = $2)
                 AND ($3::text IS NULL OR target_form = $3)
                 AND ($4::text IS NULL OR enrollment_id ILIKE $4 || '%' OR confirmation_ref ILIKE $4 || '%')
               ORDER BY updated_at DESC LIMIT $5 OFFSET $6""",
            status, outcome, form, q.strip().upper() if q else None, limit, offset)
        return [self._row(r) for r in rows]

    async def counts(self) -> dict[str, int]:
        rows = await self.pool.fetch("SELECT status, count(*) AS n FROM enrollments GROUP BY status")
        return {r["status"]: r["n"] for r in rows}

    async def recent_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            "SELECT a.actor, a.action, a.details, a.at, e.enrollment_id FROM audit_logs a "
            "LEFT JOIN enrollments e ON e.id = a.enrollment_id ORDER BY a.at DESC LIMIT $1", limit)
        return [{"enrollment_id": r["enrollment_id"], "actor": r["actor"], "action": r["action"],
                 "details": json.loads(r["details"]), "at": r["at"].isoformat()} for r in rows]

    # ------------------------------------------------------------ mapping and validation

    def _field_ad(self, enrollment: Enrollment, name: str) -> str:
        return f"{enrollment.id}:{name}"   # a sealed value only opens for its own record and field

    async def save_mapping(self, e: Enrollment, *, fields: list[FieldResult], payload: dict[str, Any],
                           outcome: str, reasons: list[dict[str, Any]], status: str, mapper: str,
                           min_confidence: float | None, meta: dict[str, Any], applicant_fp: str | None,
                           actor: str, events: list[tuple[str, dict[str, Any]]]) -> Enrollment:
        rid = str(e.id)
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM field_mappings WHERE enrollment_id = $1", e.id)
            await conn.executemany(
                """INSERT INTO field_mappings (enrollment_id, field, source_fields, value, confidence, state,
                                               assumption, method, candidates, updated_by)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                [(e.id, f.field, f.source_fields,
                  self.cipher.seal(f.value, self._field_ad(e, f.field)) if f.value is not None else None,
                  round(f.confidence, 3), f.state,
                  self.cipher.seal(f.assumption, self._field_ad(e, f.field)) if f.assumption else None,
                  f.method, f.candidates, actor if f.method == "edited" else "mapper") for f in fields])
            row = await conn.fetchrow(
                """UPDATE enrollments SET mapped_payload = $2, outcome = $3, issues = $4, status = $5, mapper = $6,
                          min_confidence = $7, mapping_meta = $8, applicant_fp = COALESCE($9, applicant_fp),
                          updated_at = now()
                   WHERE id = $1 RETURNING *""",
                e.id, self.cipher.seal(payload, rid), outcome, json.dumps(reasons), status, mapper, min_confidence,
                json.dumps(meta), applicant_fp)
            for action, details in events:
                await self._audit(conn, e.id, actor, action, details)
        return self._row(row)

    async def field_results(self, e: Enrollment) -> list[FieldResult]:
        rows = await self.pool.fetch("SELECT * FROM field_mappings WHERE enrollment_id = $1 ORDER BY id", e.id)
        out = []
        for r in rows:
            ad = self._field_ad(e, r["field"])
            out.append(FieldResult(
                field=r["field"], value=self.cipher.open(r["value"], ad) if r["value"] is not None else None,
                source_fields=list(r["source_fields"]), confidence=float(r["confidence"] or 0), state=r["state"],
                method=r["method"], assumption=self.cipher.open(r["assumption"], ad) if r["assumption"] else None,
                candidates=list(r["candidates"])))
        return out

    async def set_submission(self, e: Enrollment, *, status: str, path: str | None, ref: str | None,
                             reasons: list[dict[str, Any]], actor: str, event: tuple[str, dict[str, Any]]) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """UPDATE enrollments SET status = $2, submit_path = COALESCE($3, submit_path),
                          confirmation_ref = COALESCE($4, confirmation_ref), issues = $5, updated_at = now()
                   WHERE id = $1""", e.id, status, path, ref, json.dumps(reasons))
            await self._audit(conn, e.id, actor, event[0], event[1])

    async def set_status(self, e: Enrollment, status: str, actor: str, action: str,
                         details: dict[str, Any] | None = None, only_from: tuple[str, ...] = (),
                         issues: list[dict[str, Any]] | None = None) -> bool:
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "UPDATE enrollments SET status = $2, updated_at = now(), issues = COALESCE($4::jsonb, issues) "
                "WHERE id = $1 AND (cardinality($3::text[]) = 0 OR status = ANY($3::text[])) RETURNING id",
                e.id, status, list(only_from), json.dumps(issues) if issues is not None else None)
            if row is None:
                return False
            await self._audit(conn, e.id, actor, action, details or {})
            return True

    async def audit_by_id(self, enrollment_uuid: uuid.UUID, actor: str, action: str, details: dict[str, Any]) -> None:
        async with self.pool.acquire() as conn:
            await self._audit(conn, enrollment_uuid, actor, action, details)

    async def audit(self, enrollment: Enrollment | None, actor: str, action: str,
                    details: dict[str, Any] | None = None) -> None:
        async with self.pool.acquire() as conn:
            await self._audit(conn, enrollment.id if enrollment else None, actor, action, details or {})

    @staticmethod
    async def _audit(conn: asyncpg.Connection, enrollment_uuid: uuid.UUID | None, actor: str, action: str,
                     details: dict[str, Any]) -> None:
        await conn.execute("INSERT INTO audit_logs (enrollment_id, actor, action, details) VALUES ($1, $2, $3, $4)",
                           enrollment_uuid, actor, action, json.dumps(mask_value("details", details)))

    async def audit_trail(self, enrollment: Enrollment) -> list[dict[str, Any]]:
        rows = await self.pool.fetch("SELECT actor, action, details, at FROM audit_logs WHERE enrollment_id = $1 "
                                     "ORDER BY id", enrollment.id)
        return [{"actor": r["actor"], "action": r["action"], "details": json.loads(r["details"]),
                 "at": r["at"].isoformat()} for r in rows]
