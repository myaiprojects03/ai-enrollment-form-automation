"""Enrollments: intake as JSON, reading, re-mapping, and a reviewer's edits (operator only)."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import operator
from app.api.service import receive_and_process, view
from app.enrollments.pipeline import LockedError
from app.forms.registry import FORMS

router = APIRouter(prefix="/api")


class IntakeRequest(BaseModel):
    target_form: str = Field(description="One of GET /api/forms")
    source: Literal["json", "csv", "webhook", "pdf", "notes", "api"] = "api"
    record: dict[str, Any] = Field(min_length=1, description="The applicant record exactly as received")
    idempotency_key: str | None = Field(default=None, max_length=200)
    process: bool = Field(default=True, description="Map and validate straight away")


class FieldEdits(BaseModel):
    changes: dict[str, Any] = Field(min_length=1, description="field name -> new value (null clears it)")


@router.get("/forms")
def forms(_: str = Depends(operator)) -> list[dict[str, Any]]:
    return [f.model_dump() for f in FORMS.values()]


@router.post("/enrollments", status_code=201)
async def receive(body: IntakeRequest, request: Request, response: Response, actor: str = Depends(operator),
                  idempotency_key: str | None = Header(default=None)) -> dict[str, Any]:
    out = await receive_and_process(request, target_form=body.target_form, source=body.source, record=body.record,
                                    idempotency_key=body.idempotency_key or idempotency_key, actor=actor,
                                    process=body.process)
    if out["duplicate"]:
        response.status_code = 200
    return out


@router.get("/enrollments")
async def recent(request: Request, status: str | None = None, outcome: str | None = None, form: str | None = None,
                 q: str | None = None, limit: int = 50, offset: int = 0,
                 _: str = Depends(operator)) -> list[dict[str, Any]]:
    """The queue. Summaries only: no personal data (open one enrollment to see it, which is audited)."""
    rows = await request.app.state.enrollments.list_recent(min(max(limit, 1), 200), status, outcome=outcome,
                                                           form=form, q=q, offset=max(offset, 0))
    return [e.summary() for e in rows]


@router.get("/enrollments/counts")
async def counts(request: Request, _: str = Depends(operator)) -> dict[str, int]:
    return await request.app.state.enrollments.counts()


@router.get("/audit")
async def audit_log(request: Request, limit: int = 100, _: str = Depends(operator)) -> list[dict[str, Any]]:
    """Everything that happened, newest first: sign-ins, edits, decisions, submissions. Values are never logged."""
    return await request.app.state.enrollments.recent_audit(min(max(limit, 1), 500))


async def _get(request: Request, enrollment_id: str) -> Any:
    e = await request.app.state.enrollments.get(enrollment_id)
    if e is None:
        raise HTTPException(404, "no such enrollment")
    return e


@router.get("/enrollments/{enrollment_id}")
async def one(enrollment_id: str, request: Request, reveal: bool = False,
              actor: str = Depends(operator)) -> dict[str, Any]:
    store = request.app.state.enrollments
    e = await _get(request, enrollment_id)
    if reveal:  # personal data is decrypted only on request, and that access is itself recorded
        await store.audit(e, actor, "personal_data.viewed", {})
    out = {**view(e, await store.field_results(e), reveal), "audit": await store.audit_trail(e)}
    if reveal:
        out["source_record"], out["mapped_payload"] = e.source_record, e.mapped_payload
    return out


@router.get("/enrollments/{enrollment_id}/mapping")
async def mapping(enrollment_id: str, request: Request, actor: str = Depends(operator)) -> dict[str, Any]:
    """The mapper's output as a structured contract. Holds personal data, so reading it is audited."""
    from app.forms.registry import check_payload, get_form
    from app.mapping.result import contract
    from app.mapping.rules import applies

    store = request.app.state.enrollments
    e = await _get(request, enrollment_id)
    form = get_form(e.target_form)
    fields = await store.field_results(e)
    by_name = {f.field: f for f in fields}
    needed = {s.name for s in form.fields if s.required and applies(form, s, by_name, date.today())}
    await store.audit(e, actor, "personal_data.viewed", {"view": "mapping"})
    model, _ = check_payload(form.id, {f.field: f.value for f in fields if f.resolved}, date.today())
    return {"enrollment_id": e.enrollment_id, "target_form": e.target_form, "schema_valid": model is not None,
            **contract(fields, {s.name: s.label for s in form.fields}, needed).model_dump()}


@router.post("/enrollments/{enrollment_id}/process")
async def reprocess(enrollment_id: str, request: Request, actor: str = Depends(operator)) -> dict[str, Any]:
    """Map again from the source record (after a mapper change, say). A reviewer's edits are kept."""
    e = await _get(request, enrollment_id)
    try:
        e, _ = await request.app.state.pipeline.process(e, actor)
    except LockedError as exc:
        raise HTTPException(409, f"cannot change an enrollment that is {exc}") from None
    return view(e, await request.app.state.enrollments.field_results(e))


@router.patch("/enrollments/{enrollment_id}/fields")
async def edit_fields(enrollment_id: str, body: FieldEdits, request: Request,
                      actor: str = Depends(operator)) -> dict[str, Any]:
    """A reviewer's corrections: each edited field counts as certain, then the whole record is checked again."""
    e = await _get(request, enrollment_id)
    try:
        e, _ = await request.app.state.pipeline.edit(e, body.changes, actor)
    except LockedError as exc:
        raise HTTPException(409, f"cannot change an enrollment that is {exc}") from None
    except KeyError as exc:
        raise HTTPException(422, f"not fields of this form: {exc.args[0]}") from None
    return view(e, await request.app.state.enrollments.field_results(e))
