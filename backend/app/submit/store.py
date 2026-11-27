"""Submission runs, their screenshots (encrypted), and the learned locators."""
from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg

from app.security.crypto import FieldCipher
from app.submit.base import Shot
from app.submit.locators import Heal, Learned

MAX_SHOTS = 10


class RunInProgress(Exception):
    """Another run for this enrollment is already going (the database allows only one)."""


class RunStore:
    def __init__(self, pool: asyncpg.Pool, cipher: FieldCipher):
        self.pool, self.cipher = pool, cipher

    async def claim(self, enrollment_uuid: uuid.UUID) -> bool:
        """approved -> submitting, atomically: two workers cannot both start the same submission."""
        row = await self.pool.fetchrow("UPDATE enrollments SET status = 'submitting', updated_at = now() "
                                       "WHERE id = $1 AND status = 'approved' RETURNING id", enrollment_uuid)
        return row is not None

    async def start(self, enrollment_uuid: uuid.UUID, path: str, options: dict[str, Any], actor: str) -> uuid.UUID:
        async with self.pool.acquire() as conn, conn.transaction():
            attempt = await conn.fetchval("SELECT COALESCE(MAX(attempt), 0) + 1 FROM submission_runs "
                                          "WHERE enrollment_id = $1", enrollment_uuid)
            try:
                return await conn.fetchval(
                    "INSERT INTO submission_runs (enrollment_id, attempt, path, options, actor) "
                    "VALUES ($1, $2, $3, $4, $5) RETURNING id", enrollment_uuid, attempt, path, json.dumps(options),
                    actor)
            except asyncpg.UniqueViolationError:
                raise RunInProgress() from None

    async def finish(self, run_id: uuid.UUID, status: str, *, error_code: str | None = None,
                     error_detail: str | None = None, confirmation_ref: str | None = None,
                     steps: list[dict[str, Any]] | None = None, shots: list[Shot] | None = None) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """UPDATE submission_runs SET status = $2, error_code = $3, error_detail = $4, confirmation_ref = $5,
                          steps = $6, finished_at = now(),
                          duration_ms = (EXTRACT(EPOCH FROM (now() - started_at)) * 1000)::int
                   WHERE id = $1""",
                run_id, status, error_code, error_detail, confirmation_ref, json.dumps(steps or []))
            for seq, shot in enumerate((shots or [])[-MAX_SHOTS:], start=1):
                await conn.execute(
                    "INSERT INTO run_artifacts (run_id, seq, label, content, bytes) VALUES ($1, $2, $3, $4, $5)",
                    run_id, seq, shot.label, self.cipher.seal_bytes(shot.jpeg, f"{run_id}:{seq}"), len(shot.jpeg))

    async def runs(self, enrollment_uuid: uuid.UUID) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            """SELECT r.*, COALESCE(json_agg(json_build_object('id', a.id, 'seq', a.seq, 'label', a.label,
                                                               'bytes', a.bytes) ORDER BY a.seq)
                                    FILTER (WHERE a.id IS NOT NULL), '[]') AS artifacts
               FROM submission_runs r LEFT JOIN run_artifacts a ON a.run_id = r.id
               WHERE r.enrollment_id = $1 GROUP BY r.id ORDER BY r.attempt""", enrollment_uuid)
        return [{"run_id": str(r["id"]), "attempt": r["attempt"], "path": r["path"], "status": r["status"],
                 "error_code": r["error_code"], "error_detail": r["error_detail"],
                 "confirmation_ref": r["confirmation_ref"], "steps": json.loads(r["steps"]),
                 "options": json.loads(r["options"]), "actor": r["actor"],
                 "started_at": r["started_at"].isoformat(),
                 "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
                 "duration_ms": r["duration_ms"], "screenshots": json.loads(r["artifacts"])} for r in rows]

    async def history(self, *, status: str | None = None, form: str | None = None, q: str | None = None,
                      limit: int = 100) -> list[dict[str, Any]]:
        """Every attempt across enrollments, newest first, with the retry count of its submission."""
        rows = await self.pool.fetch(
            """SELECT r.id, r.attempt, r.path, r.status, r.error_code, r.error_detail, r.confirmation_ref,
                      r.started_at, r.duration_ms, r.actor, r.options, e.enrollment_id, e.target_form,
                      e.status AS enrollment_status,
                      (SELECT count(*) FROM run_artifacts a WHERE a.run_id = r.id) AS screenshots,
                      (SELECT count(*) FROM submission_runs x WHERE x.enrollment_id = r.enrollment_id
                         AND x.attempt < r.attempt AND x.status IN ('failed', 'halted')) AS retries_before
               FROM submission_runs r JOIN enrollments e ON e.id = r.enrollment_id
               WHERE ($1::text IS NULL OR r.status = $1) AND ($2::text IS NULL OR e.target_form = $2)
                 AND ($3::text IS NULL OR e.enrollment_id ILIKE $3 || '%' OR r.confirmation_ref ILIKE $3 || '%')
               ORDER BY r.started_at DESC LIMIT $4""", status, form, q.strip().upper() if q else None, limit)
        return [{"run_id": str(r["id"]), "enrollment_id": r["enrollment_id"], "target_form": r["target_form"],
                 "enrollment_status": r["enrollment_status"], "attempt": r["attempt"], "path": r["path"],
                 "status": r["status"], "retries_before": r["retries_before"], "error_code": r["error_code"],
                 "error_detail": r["error_detail"], "confirmation_ref": r["confirmation_ref"],
                 "started_at": r["started_at"].isoformat(), "duration_ms": r["duration_ms"], "actor": r["actor"],
                 "options": json.loads(r["options"]), "screenshots": r["screenshots"]} for r in rows]

    async def screenshot(self, run_id: uuid.UUID, artifact_id: int) -> tuple[uuid.UUID, bytes] | None:
        row = await self.pool.fetchrow(
            "SELECT a.seq, a.content, r.enrollment_id FROM run_artifacts a JOIN submission_runs r ON r.id = a.run_id "
            "WHERE a.run_id = $1 AND a.id = $2", run_id, artifact_id)
        if row is None:
            return None
        return row["enrollment_id"], self.cipher.open_bytes(row["content"], f"{run_id}:{row['seq']}")

    async def interrupted(self, older_than_s: int) -> list[uuid.UUID]:
        """Runs left 'running' by a worker that stopped: closed, and their enrollments returned to approved."""
        async with self.pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(
                "UPDATE submission_runs SET status = 'failed', error_code = 'INTERRUPTED', "
                "error_detail = 'the worker stopped during this run', finished_at = now() "
                "WHERE status = 'running' AND started_at < now() - make_interval(secs => $1) RETURNING enrollment_id",
                older_than_s)
            ids = list({r["enrollment_id"] for r in rows})
            stuck = await conn.fetch(
                "UPDATE enrollments e SET status = 'approved', updated_at = now() WHERE status = 'submitting' "
                "AND updated_at < now() - make_interval(secs => $1) AND NOT EXISTS (SELECT 1 FROM submission_runs r "
                "WHERE r.enrollment_id = e.id AND r.status = 'running') RETURNING id", older_than_s)
            return list({*ids, *(r["id"] for r in stuck)})

    # ---------------------------------------------------------------- learned locators

    async def locators(self, form_id: str) -> dict[str, Learned]:
        rows = await self.pool.fetch("SELECT target, strategy, arg FROM locator_cache WHERE form_id = $1", form_id)
        return {r["target"]: Learned(r["strategy"], r["arg"]) for r in rows}

    async def learn(self, form_id: str, learned: dict[str, Learned], heals: list[Heal], used: dict[str, str]) -> None:
        healed = {h.target for h in heals}
        async with self.pool.acquire() as conn, conn.transaction():
            for target, item in learned.items():
                await conn.execute(
                    """INSERT INTO locator_cache (form_id, target, strategy, arg, hits, healed_at)
                       VALUES ($1, $2, $3, $4, 1, CASE WHEN $5 THEN now() END)
                       ON CONFLICT (form_id, target) DO UPDATE SET strategy = $3, arg = $4, hits = 1,
                           healed_at = CASE WHEN $5 THEN now() ELSE locator_cache.healed_at END, updated_at = now()""",
                    form_id, target, item.strategy, item.arg, target in healed)
            for target in set(used) - set(learned):
                await conn.execute("UPDATE locator_cache SET hits = hits + 1, updated_at = now() "
                                   "WHERE form_id = $1 AND target = $2", form_id, target)
