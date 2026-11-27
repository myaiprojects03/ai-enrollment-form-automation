"""Intake: every record enters here, exactly once.

Two gates make a replay (a retried webhook, a re-uploaded CSV row, a double click) harmless:
1. Redis: SET NX on the idempotency key. A second worker that receives the same record while the first is
   still writing it backs off at once, without touching the database.
2. Postgres: a UNIQUE idempotency_key. Even if Redis were emptied, the database refuses the second row and the
   first enrollment is returned.

Without a key from the sender, the key is a keyed hash of the form and the record's canonical JSON: the same
record sent twice is recognised; a changed record is a new enrollment.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.enrollments.store import Enrollment, EnrollmentStore
from app.forms.registry import get_form
from app.security.crypto import Fingerprinter
from app.shared.store import SharedStore

PENDING = "pending"


class DuplicateInFlight(Exception):
    """The same key is being processed right now by another request or worker."""


@dataclass
class IntakeResult:
    enrollment: Enrollment
    created: bool
    possible_duplicates: list[str]


def derived_key(fingerprints: Fingerprinter, target_form: str, record: dict[str, Any]) -> str:
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    return "auto:" + fingerprints.digest(f"{target_form}\n{canonical}")[:40]


def find_email(record: dict[str, Any]) -> str | None:
    for key, value in record.items():
        if "mail" in key.lower() and "guardian" not in key.lower() and "parent" not in key.lower() \
                and isinstance(value, str) and "@" in value:
            return value
    return None


class Intake:
    def __init__(self, store: EnrollmentStore, shared: SharedStore, fingerprints: Fingerprinter, ttl_s: int):
        self.store = store
        self.shared = shared
        self.fingerprints = fingerprints
        self.ttl_s = ttl_s

    async def receive(self, *, target_form: str, source: str, record: dict[str, Any], idempotency_key: str | None,
                      actor: str) -> IntakeResult:
        get_form(target_form)  # unknown forms are refused before anything is stored
        key = (idempotency_key or "").strip() or derived_key(self.fingerprints, target_form, record)
        gate = f"idem:{key}"
        known = await self.shared.get(gate)
        if known and known != PENDING:
            existing = await self.store.get(known)
            if existing:
                return IntakeResult(existing, False, [])
        if not await self.shared.add(gate, PENDING, ttl_s=60):
            existing = await self.store.get_by_key(key)
            if existing:
                return IntakeResult(existing, False, [])
            raise DuplicateInFlight(key)
        try:
            email = find_email(record)
            fp = self.fingerprints.of("email", email) if email else None
            enrollment, created = await self.store.create(idempotency_key=key, source=source, target_form=target_form,
                                                          record=record, applicant_fp=fp, actor=actor)
        except BaseException:
            await self.shared.delete(gate)
            raise
        await self.shared.put(gate, enrollment.enrollment_id, self.ttl_s)
        dupes = await self.store.same_applicant(target_form, fp, enrollment.id) if (fp and created) else []
        if dupes:
            await self.store.audit(enrollment, "system", "enrollment.possible_duplicate", {"others": dupes})
        return IntakeResult(enrollment, created, dupes)
