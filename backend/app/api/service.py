"""What every intake route does: receive once, then map and validate (only when the record is new)."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from app.enrollments.intake import DuplicateInFlight
from app.enrollments.store import Enrollment
from app.forms.registry import FORMS, get_form
from app.mapping.result import FieldResult


async def receive_and_process(request: Request, *, target_form: str, source: str, record: dict[str, Any],
                              idempotency_key: str | None, actor: str, process: bool = True) -> dict[str, Any]:
    if target_form not in FORMS:
        raise HTTPException(422, f"unknown target_form; known: {', '.join(FORMS)}")
    state = request.app.state
    try:
        result = await state.intake.receive(target_form=target_form, source=source, record=record,
                                            idempotency_key=idempotency_key, actor=actor)
    except DuplicateInFlight:
        raise HTTPException(409, "the same record is being received right now; retry shortly") from None
    e: Enrollment = result.enrollment
    if result.created and process:
        e, _ = await state.pipeline.process(e, actor)
    fields = await state.enrollments.field_results(e)
    return {**view(e, fields), "duplicate": not result.created, "possible_duplicates": result.possible_duplicates}


def field_view(form_id: str, f: FieldResult, reveal: bool) -> dict[str, Any]:
    spec = get_form(form_id).field(f.field)
    out: dict[str, Any] = {"field": f.field, "label": spec.label, "required": spec.required, "state": f.state,
                           "confidence": round(f.confidence, 3), "method": f.method,
                           "source_fields": f.source_fields, "candidates": f.candidates,
                           "has_assumption": bool(f.assumption)}
    if reveal:
        out["value"], out["assumption"] = f.value, f.assumption
    return out


def view(e: Enrollment, fields: list[FieldResult], reveal: bool = False) -> dict[str, Any]:
    return {**e.summary(), "mapping": e.mapping_meta, "fields": [field_view(e.target_form, f, reveal) for f in fields]}
