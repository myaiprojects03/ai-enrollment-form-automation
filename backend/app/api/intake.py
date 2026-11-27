"""Other ways in: file upload (CSV, JSON, PDF, text), pasted notes, and a signed webhook for n8n or a CRM."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field, ValidationError

from app.api.deps import operator
from app.api.service import receive_and_process
from app.config import get_settings
from app.ingest.parsers import MAX_BYTES, ParseError, parse_file, parse_notes

router = APIRouter(prefix="/api")
CONCURRENCY = 4   # records mapped at once from one upload (each may call the AI mapper)


def _brief(out: dict[str, Any], row: int) -> dict[str, Any]:
    return {"row": row, "enrollment_id": out["enrollment_id"], "duplicate": out["duplicate"],
            "status": out["status"], "outcome": out["outcome"],
            "reasons": [r for r in out["reasons"] if r["severity"] != "info"]}


@router.post("/intake/upload")
async def upload(request: Request, target_form: Annotated[str, Form()], file: Annotated[UploadFile, File()],
                 actor: str = Depends(operator)) -> dict[str, Any]:
    data = await file.read(MAX_BYTES + 1)
    try:
        parsed = parse_file(file.filename or "", file.content_type or "", data)
    except ParseError as exc:
        raise HTTPException(422, str(exc)) from None
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(row: int, record: dict[str, Any]) -> dict[str, Any]:
        async with gate:
            out = await receive_and_process(request, target_form=target_form, source=parsed.source, record=record,
                                            idempotency_key=None, actor=actor)
            return _brief(out, row)

    results = await asyncio.gather(*(one(i, r) for i, r in enumerate(parsed.records, start=1)))
    counts = Counter(r["outcome"] or "UNPROCESSED" for r in results)
    return {"source": parsed.source, "records": len(results), "warnings": parsed.warnings,
            "outcomes": dict(counts), "results": results}


class NotesRequest(BaseModel):
    target_form: str
    text: str = Field(min_length=1, max_length=20000)
    idempotency_key: str | None = Field(default=None, max_length=200)


@router.post("/intake/notes", status_code=201)
async def notes(body: NotesRequest, request: Request, response: Response,
                actor: str = Depends(operator)) -> dict[str, Any]:
    try:
        record = parse_notes(body.text).records[0]
    except ParseError as exc:
        raise HTTPException(422, str(exc)) from None
    out = await receive_and_process(request, target_form=body.target_form, source="notes", record=record,
                                    idempotency_key=body.idempotency_key, actor=actor)
    if out["duplicate"]:
        response.status_code = 200
    return out


class WebhookBody(BaseModel):
    target_form: str
    record: dict[str, Any] = Field(min_length=1)
    idempotency_key: str | None = Field(default=None, max_length=200)


def signature_ok(secret: str, body: bytes, header: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.strip())


@router.post("/webhooks/intake", status_code=201)
async def webhook(request: Request, response: Response, x_signature: str = Header(default=""),
                  idempotency_key: str | None = Header(default=None)) -> dict[str, Any]:
    """For n8n, a CRM or a form tool. Signed instead of the operator token: X-Signature: sha256=<hex HMAC of body>.
    The sender's retries are safe: send the same Idempotency-Key (or the same body) and the first result returns."""
    secret = get_settings().webhook_secret
    if not secret:
        raise HTTPException(503, "the intake webhook is not configured")
    raw = await request.body()
    if not signature_ok(secret, raw, x_signature):
        raise HTTPException(401, "bad or missing X-Signature")
    try:
        body = WebhookBody.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError):
        raise HTTPException(422, "expected {target_form, record, idempotency_key?}") from None
    out = await receive_and_process(request, target_form=body.target_form, source="webhook", record=body.record,
                                    idempotency_key=body.idempotency_key or idempotency_key, actor="webhook")
    if out["duplicate"]:
        response.status_code = 200
    return out
