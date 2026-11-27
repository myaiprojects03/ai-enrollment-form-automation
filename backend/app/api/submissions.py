"""A person's decision (approve, reject), submitting to the portal, and the record of every attempt."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import operator
from app.config import get_settings
from app.forms.registry import get_form
from app.security.masking import mask_text
from app.submit.base import TestModes
from app.submit.dispatch import trigger_worker
from app.submit.runner import InFlight, NotReady

router = APIRouter(prefix="/api")


async def _get(request: Request, enrollment_id: str) -> Any:
    e = await request.app.state.enrollments.get(enrollment_id)
    if e is None:
        raise HTTPException(404, "no such enrollment")
    return e


class Decision(BaseModel):
    note: str = Field(default="", max_length=500)


@router.post("/enrollments/{enrollment_id}/approve")
async def approve(enrollment_id: str, body: Decision, request: Request,
                  actor: str = Depends(operator)) -> dict[str, Any]:
    """A reviewer's sign-off. Not possible while a blocking problem is open: fix the fields first."""
    store = request.app.state.enrollments
    e = await _get(request, enrollment_id)
    blocking = [r for r in e.issues if r.get("severity") == "block"]
    if blocking:
        raise HTTPException(409, f"{len(blocking)} blocking problem(s) must be fixed before approval")
    if e.status == "approved":
        return e.summary()
    # The reviewer has looked at every open point: record that they accepted them, and who.
    accepted = [{**r, "accepted_by": actor} if r.get("severity") == "review" else r for r in e.issues]
    ok = await store.set_status(e, "approved", actor, "enrollment.approved",
                                {"note": mask_text(body.note), "accepted": sorted({r["code"] for r in e.issues
                                                                                   if r.get("severity") == "review"})},
                                only_from=("needs_review", "failed"), issues=accepted)
    if not ok:
        raise HTTPException(409, f"an enrollment that is {e.status} cannot be approved")
    return (await _get(request, enrollment_id)).summary()


@router.post("/enrollments/{enrollment_id}/reject")
async def reject(enrollment_id: str, body: Decision, request: Request,
                 actor: str = Depends(operator)) -> dict[str, Any]:
    store = request.app.state.enrollments
    e = await _get(request, enrollment_id)
    ok = await store.set_status(e, "rejected", actor, "enrollment.rejected", {"note": mask_text(body.note)},
                                only_from=("received", "mapped", "needs_review", "blocked", "approved", "failed"))
    if not ok:
        raise HTTPException(409, f"an enrollment that is {e.status} cannot be rejected")
    return (await _get(request, enrollment_id)).summary()


class SubmitRequest(BaseModel):
    path: Literal["api", "browser"] | None = Field(default=None, description="Default: the API if the portal has one")
    wait: bool = Field(default=False, description="Wait for the result instead of running in the background")
    variant: Literal["", "b"] = Field(default="", description="Test mode: the portal's drifted page")
    chaos: Literal["", "slow", "flaky", "down", "lost", "captcha"] = Field(default="", description="Test mode")


@router.post("/enrollments/{enrollment_id}/submit")
async def submit(enrollment_id: str, body: SubmitRequest, request: Request, response: Response,
                 actor: str = Depends(operator)) -> dict[str, Any]:
    settings = get_settings()
    modes = TestModes(variant=body.variant, chaos=body.chaos)
    if (modes.variant or modes.chaos) and (settings.is_production or not settings.allow_test_modes):
        raise HTTPException(403, "test modes are switched off here")
    e = await _get(request, enrollment_id)
    if e.status == "submitted":
        return {"enrollment_id": e.enrollment_id, "status": e.status, "confirmation_ref": e.confirmation_ref,
                "already_submitted": True}
    if e.status != "approved":
        raise HTTPException(409, f"only approved enrollments are submitted; this one is {e.status}")
    submitter = request.app.state.submitter
    path = body.path or ("api" if get_form(e.target_form).api_path else "browser")
    if settings.submit_mode == "dispatch" and path == "browser":
        # Serverless: this process has no browser and stops when it answers. The worker picks approved records up.
        sent = await trigger_worker(settings.github_dispatch_repo, settings.github_dispatch_token)
        await request.app.state.enrollments.audit(e, actor, "submission.queued", {"via": "worker", "triggered": sent})
        response.status_code = 202
        return {"enrollment_id": e.enrollment_id, "status": e.status, "queued": True, "via": "worker",
                "note": "The web-form submission runs in the worker within a few minutes."}

    async def go() -> dict[str, Any]:
        try:
            return (await submitter.submit(e, actor, body.path, modes)).as_dict()
        except NotReady as exc:
            raise HTTPException(409, f"only approved enrollments are submitted; this one is {exc}") from None
        except InFlight:
            raise HTTPException(409, "this enrollment is being submitted right now") from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    if body.wait or settings.submit_mode == "dispatch":   # serverless: finish the API submission before answering
        return await go()
    task = asyncio.create_task(go())
    request.app.state.tasks.add(task)
    task.add_done_callback(request.app.state.tasks.discard)
    response.status_code = 202
    return {"enrollment_id": e.enrollment_id, "status": "submitting", "queued": True}


@router.get("/enrollments/{enrollment_id}/runs")
async def runs(enrollment_id: str, request: Request, _: str = Depends(operator)) -> list[dict[str, Any]]:
    e = await _get(request, enrollment_id)
    return await request.app.state.runs.runs(e.id)


@router.get("/runs")
async def run_history(request: Request, status: str | None = None, form: str | None = None, q: str | None = None,
                      limit: int = 100, _: str = Depends(operator)) -> list[dict[str, Any]]:
    """Run history: every submission attempt, filterable by status, portal and enrollment ID or reference."""
    return await request.app.state.runs.history(status=status, form=form, q=q, limit=min(max(limit, 1), 500))


@router.get("/runs/{run_id}/screenshots/{artifact_id}")
async def screenshot(run_id: uuid.UUID, artifact_id: int, request: Request,
                     actor: str = Depends(operator)) -> Response:
    """A screenshot shows personal data: it is decrypted on request, and the viewing is audited."""
    found = await request.app.state.runs.screenshot(run_id, artifact_id)
    if found is None:
        raise HTTPException(404, "no such screenshot")
    enrollment_uuid, jpeg = found
    await request.app.state.enrollments.audit_by_id(enrollment_uuid, actor, "screenshot.viewed",
                                                    {"run_id": str(run_id), "screenshot": artifact_id})
    return Response(jpeg, media_type="image/jpeg", headers={"cache-control": "private, no-store"})
