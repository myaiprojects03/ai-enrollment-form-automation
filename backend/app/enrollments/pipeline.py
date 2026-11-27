"""Map, then validate, then store the result: the step between intake and submission.

process() maps a record from scratch but keeps a reviewer's edits; edit() applies a reviewer's changes and checks
again without re-mapping. Both end in the same place: field mappings (encrypted), the payload, the outcome with its
reasons, and the status, written in one transaction with the audit entries.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.enrollments.store import Enrollment, EnrollmentStore
from app.forms.registry import get_form
from app.mapping.mapper import Mapper
from app.mapping.result import FieldResult, MappingResult
from app.mapping.values import ConvError, convert
from app.security.crypto import Fingerprinter
from app.validation.outcome import Verdict, judge

LOCKED = {"submitting", "submitted", "rejected"}


class LockedError(Exception):
    """The enrollment is past the point where its data may change."""


class Pipeline:
    def __init__(self, store: EnrollmentStore, mapper: Mapper, fingerprints: Fingerprinter, threshold: float):
        self.store, self.mapper, self.fingerprints, self.threshold = store, mapper, fingerprints, threshold

    async def process(self, e: Enrollment, actor: str, today: date | None = None) -> tuple[Enrollment, Verdict]:
        if e.status in LOCKED:
            raise LockedError(e.status)
        today = today or date.today()
        form = get_form(e.target_form)
        mapping = await self.mapper.map(form, e.source_record, today)
        for kept in await self.store.field_results(e):
            if kept.method == "edited" and kept.field in mapping.fields:
                mapping.fields[kept.field] = kept
        return await self._finish(e, mapping, actor, today, "mapping.completed")

    async def edit(self, e: Enrollment, changes: dict[str, Any], actor: str,
                   today: date | None = None) -> tuple[Enrollment, Verdict]:
        if e.status in LOCKED:
            raise LockedError(e.status)
        today = today or date.today()
        form = get_form(e.target_form)
        unknown = [k for k in changes if k not in form.names]
        if unknown:
            raise KeyError(", ".join(unknown))
        stored = {f.field: f for f in await self.store.field_results(e)}
        if not stored:   # never mapped: map first so the edit lands on a full picture
            _, _ = await self.process(e, actor, today)
            e = await self.store.get(e.enrollment_id) or e
            stored = {f.field: f for f in await self.store.field_results(e)}
        fields = {name: stored.get(name, FieldResult(field=name)) for name in form.names}
        for name, raw in changes.items():
            spec = form.field(name)
            res = FieldResult(field=name, state="edited", method="edited", confidence=1.0)
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                res.value = None
            else:
                try:
                    res.value = convert(spec, raw, today).value   # same normalising as the mapper
                except ConvError:
                    res.value = raw                                # validation will say what is wrong
            fields[name] = res
        meta = e.mapping_meta or {}
        mapping = MappingResult(fields=fields, unused_source_fields=meta.get("unused_source_fields", []),
                                mapper=e.mapper or "rules", llm_used=meta.get("llm_used", False),
                                llm_error=meta.get("llm_error"), llm_needed=meta.get("llm_needed", False))
        return await self._finish(e, mapping, actor, today, "fields.edited", edited=sorted(changes))

    async def _finish(self, e: Enrollment, mapping: MappingResult, actor: str, today: date, action: str,
                      edited: list[str] | None = None) -> tuple[Enrollment, Verdict]:
        form = get_form(e.target_form)
        email = mapping.fields.get("email")
        fp = self.fingerprints.of("email", str(email.value)) if email and email.resolved else None
        dupes = await self.store.same_applicant(e.target_form, fp, e.id) if fp else []
        verdict = judge(form, mapping, today, self.threshold, dupes)
        low = sorted(n for n, f in mapping.fields.items() if f.resolved and f.confidence < self.threshold)
        details: dict[str, Any] = {
            "mapper": mapping.mapper, "llm_used": mapping.llm_used, "llm_error": mapping.llm_error,
            "mapped": sum(1 for f in mapping.fields.values() if f.resolved), "below_threshold": low,
            "min_confidence": mapping.min_confidence,
        }
        if edited:
            details = {"fields": edited}
        events = [(action, details),
                  ("validation.outcome", {"outcome": verdict.outcome.value, "status": verdict.status,
                                          "codes": sorted({r.code for r in verdict.reasons})})]
        meta = {"unused_source_fields": mapping.unused_source_fields, "llm_used": mapping.llm_used,
                "llm_error": mapping.llm_error, "llm_needed": mapping.llm_needed}
        saved = await self.store.save_mapping(
            e, fields=list(mapping.fields.values()), payload=verdict.payload, outcome=verdict.outcome.value,
            reasons=verdict.reasons_json(), status=verdict.status, mapper=mapping.mapper,
            min_confidence=mapping.min_confidence, meta=meta, applicant_fp=fp, actor=actor, events=events)
        return saved, verdict
