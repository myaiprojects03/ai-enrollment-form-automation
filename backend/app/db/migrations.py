"""Versioned database migrations, applied at server start under an advisory lock (so two instances never
migrate at once). To change the schema, append a new (version, sql) entry; never edit an applied one.

Personal data lives only in the BYTEA columns, encrypted by app/security/crypto.py. Everything else
(statuses, codes, field names, timings) is safe to read and to show in logs.
"""
from __future__ import annotations

import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg

log = logging.getLogger(__name__)

STATUSES = ("received", "mapped", "needs_review", "blocked", "approved", "rejected", "submitting", "submitted",
            "failed")

MIGRATIONS: list[tuple[int, str]] = [
    (1, f"""
        CREATE TABLE enrollments (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            enrollment_id    TEXT NOT NULL UNIQUE,              -- ENR-XXXXXXXX, shown to people
            idempotency_key  TEXT NOT NULL UNIQUE,              -- a replayed intake never creates a second row
            source           TEXT NOT NULL CHECK (source IN ('json', 'csv', 'webhook', 'pdf', 'notes', 'api')),
            target_form      TEXT NOT NULL,
            status           TEXT NOT NULL DEFAULT 'received' CHECK (status IN {STATUSES!r}),
            outcome          TEXT CHECK (outcome IN ('PASS', 'NEEDS_REVIEW', 'BLOCKED')),
            issues           JSONB NOT NULL DEFAULT '[]',       -- field names and codes only, never values
            source_record    BYTEA NOT NULL,                    -- encrypted
            mapped_payload   BYTEA,                             -- encrypted
            applicant_fp     TEXT,                              -- keyed fingerprint of the email: finds duplicates
            submit_path      TEXT CHECK (submit_path IN ('api', 'browser')),
            confirmation_ref TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX enrollments_status ON enrollments (status, updated_at DESC);
        CREATE INDEX enrollments_applicant ON enrollments (target_form, applicant_fp);

        CREATE TABLE field_mappings (
            id             BIGSERIAL PRIMARY KEY,
            enrollment_id  UUID NOT NULL REFERENCES enrollments(id) ON DELETE CASCADE,
            field          TEXT NOT NULL,
            source_fields  TEXT[] NOT NULL DEFAULT '{{}}',     -- which source keys it came from
            value          BYTEA,                            -- encrypted
            confidence     REAL CHECK (confidence BETWEEN 0 AND 1),
            state          TEXT NOT NULL CHECK (state IN ('mapped', 'ambiguous', 'unmapped', 'edited')),
            assumption     BYTEA,                            -- encrypted: may quote the source
            updated_by     TEXT NOT NULL DEFAULT 'mapper',
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (enrollment_id, field)
        );

        CREATE TABLE submission_runs (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            enrollment_id    UUID NOT NULL REFERENCES enrollments(id) ON DELETE CASCADE,
            attempt          INT NOT NULL,
            path             TEXT NOT NULL CHECK (path IN ('api', 'browser')),
            status           TEXT NOT NULL DEFAULT 'running'
                             CHECK (status IN ('running', 'succeeded', 'failed', 'halted')),
            error_code       TEXT,
            error_detail     TEXT,                           -- masked before it is stored
            confirmation_ref TEXT,
            screenshot_key   TEXT,                           -- where the pre-submission screenshot is kept
            started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at      TIMESTAMPTZ,
            duration_ms      INT,
            UNIQUE (enrollment_id, attempt)
        );
        -- At most one run per enrollment can be in progress: a second worker cannot start a parallel submit.
        CREATE UNIQUE INDEX submission_runs_one_running ON submission_runs (enrollment_id) WHERE status = 'running';

        CREATE TABLE audit_logs (
            id             BIGSERIAL PRIMARY KEY,
            enrollment_id  UUID REFERENCES enrollments(id) ON DELETE CASCADE,
            actor          TEXT NOT NULL,                    -- 'system', 'mapper', 'worker', or a reviewer's email
            action         TEXT NOT NULL,
            details        JSONB NOT NULL DEFAULT '{{}}',    -- masked: no personal values
            at             TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX audit_logs_enrollment ON audit_logs (enrollment_id, id);
        CREATE INDEX audit_logs_recent ON audit_logs (at DESC);
    """),
    (2, """
        -- Phase 2: mapping and validation.
        ALTER TABLE enrollments
            ADD COLUMN mapper         TEXT,                     -- rules, or rules+<provider:model>
            ADD COLUMN min_confidence REAL,
            ADD COLUMN mapping_meta   JSONB NOT NULL DEFAULT '{}';   -- unused source columns, AI status: no values
        ALTER TABLE field_mappings
            ADD COLUMN method     TEXT NOT NULL DEFAULT 'none'
                CHECK (method IN ('rule', 'derived', 'llm', 'default', 'edited', 'none')),
            ADD COLUMN candidates TEXT[] NOT NULL DEFAULT '{}';      -- other source columns or option values
        CREATE INDEX enrollments_outcome ON enrollments (outcome, updated_at DESC);
    """),
    (3, """
        -- Phase 3: submission.
        ALTER TABLE submission_runs
            ADD COLUMN steps   JSONB NOT NULL DEFAULT '[]',    -- per page: fields filled, locators used. No values.
            ADD COLUMN options JSONB NOT NULL DEFAULT '{}',    -- test modes asked for (variant, chaos)
            ADD COLUMN actor   TEXT NOT NULL DEFAULT 'system';
        CREATE TABLE run_artifacts (
            id          BIGSERIAL PRIMARY KEY,
            run_id      UUID NOT NULL REFERENCES submission_runs(id) ON DELETE CASCADE,
            seq         INT NOT NULL,
            label       TEXT NOT NULL,                         -- "page 2 filled", "confirmation", "failure"
            content     BYTEA NOT NULL,                        -- encrypted JPEG: screenshots show personal data
            bytes       INT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (run_id, seq)
        );
        -- Locators that worked, learned per form and element: tried first next time, so a healed page stays fast.
        CREATE TABLE locator_cache (
            form_id     TEXT NOT NULL,
            target      TEXT NOT NULL,                         -- a field, a field option, or a button
            strategy    TEXT NOT NULL,
            arg         TEXT NOT NULL,
            hits        INT NOT NULL DEFAULT 0,
            healed_at   TIMESTAMPTZ,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (form_id, target)
        );
    """),
]

_LOCK_ID = 7_301_552


async def migrate(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute("SELECT pg_advisory_lock($1)", _LOCK_ID)
        try:
            await conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                               "version INT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
            done = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
            for version, sql in MIGRATIONS:
                if version in done:
                    continue
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", version)
                log.info("applied database migration %d", version)
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", _LOCK_ID)


def normalize_dsn(dsn: str) -> str:
    """Accept connection strings as hosted providers (Neon) show them: drop `channel_binding` (unknown to
    asyncpg) and use the direct host instead of the pooler (PgBouncer breaks the migration lock)."""
    parts = urlsplit(dsn)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "channel_binding"]
    netloc = parts.netloc
    if "-pooler." in netloc and "neon.tech" in netloc:
        netloc = netloc.replace("-pooler.", ".", 1)
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), parts.fragment))


async def connect(dsn: str) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(normalize_dsn(dsn), min_size=1, max_size=10, timeout=10,
                                     max_inactive_connection_lifetime=60)
    await migrate(pool)
    return pool
