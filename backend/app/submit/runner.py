"""One enrollment to the portal, exactly once.

Order of events:
1. Only an approved enrollment is submitted, and only one worker at a time: a Redis lock, then an atomic
   approved -> submitting update in Postgres, then a database rule allowing one running run per enrollment.
2. Before sending anything, ask the portal whether it already has this applicant (an earlier run may have got
   through without us hearing back). If it does, keep that record.
3. Try: the API where the portal has one, otherwise the browser. A temporary failure is retried with backoff
   (2 s, 4 s, ... plus jitter), and before each retry the portal is asked again, so a reply that was lost never turns
   into a second submission. If the API keeps failing, the last attempt goes through the browser.
4. On success, read the record back from the portal and compare it with what was sent, field by field.
5. A refusal (bad field), a security check, or a value that would not stick goes back to a person with the reason.
   Every attempt is a run with its steps and screenshots; the enrollment's audit trail records the outcome.
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.enrollments.store import Enrollment, EnrollmentStore
from app.forms.base import FormSpec
from app.forms.registry import get_form
from app.security.masking import mask_text
from app.shared.store import SharedStore
from app.submit.base import HUMAN_CHECK, NOT_SET, REJECTED, UNAVAILABLE, AttemptResult, SubmitError, TestModes
from app.submit.compare import mismatches
from app.submit.locators import Resolver
from app.submit.portal_api import PortalAPI
from app.submit.store import RunInProgress, RunStore

log = logging.getLogger(__name__)
LOCK_TTL_S = 900
TO_A_PERSON = {REJECTED, HUMAN_CHECK, NOT_SET}
SUBMISSION_CODES = {"PORTAL_REJECTED", "HUMAN_CHECK_REQUIRED", "SUBMISSION_FAILED", "READBACK_MISMATCH",
                    "READBACK_UNAVAILABLE", "ADOPTED_EXISTING"}


async def post_alert(url: str, text: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(url, json={"text": text})
    except httpx.HTTPError:
        log.warning("could not send the alert for a failed submission")


class NotReady(Exception):
    """Only approved enrollments are submitted."""


class InFlight(Exception):
    """This enrollment is being submitted right now."""


class BrowserPath(Protocol):
    async def submit(self, form: FormSpec, payload: dict[str, Any], modes: TestModes,
                     resolver: Resolver) -> AttemptResult: ...


@dataclass
class Summary:
    enrollment_id: str
    status: str
    path: str | None = None
    confirmation_ref: str | None = None
    attempts: int = 0
    adopted: bool = False
    healed: list[dict[str, str]] = field(default_factory=list)
    readback: str | None = None            # matched | mismatch | unavailable
    error: dict[str, str] | None = None
    already_submitted: bool = False

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class Submitter:
    def __init__(self, enrollments: EnrollmentStore, runs: RunStore, shared: SharedStore, api: PortalAPI,
                 browser: BrowserPath, *, max_attempts: int = 3, backoff_s: float = 2.0, sleep: Any = asyncio.sleep,
                 alert_url: str = ""):
        self.enrollments, self.runs, self.shared, self.api, self.browser = enrollments, runs, shared, api, browser
        self.max_attempts, self.backoff_s, self.sleep = max(1, max_attempts), backoff_s, sleep
        self.alert_url = alert_url

    async def submit(self, e: Enrollment, actor: str, path: str | None = None,
                     modes: TestModes | None = None) -> Summary:
        modes = modes or TestModes()
        if e.status == "submitted":
            return Summary(e.enrollment_id, e.status, e.submit_path, e.confirmation_ref, already_submitted=True)
        if e.status != "approved":
            raise NotReady(e.status)
        form = get_form(e.target_form)
        chosen = path or ("api" if form.api_path else "browser")
        if chosen == "api" and not form.api_path:
            raise ValueError(f"{form.portal} has no submission API; use the browser path")
        lock = f"submit:{e.id}"
        if not await self.shared.add(lock, actor, LOCK_TTL_S):
            raise InFlight(e.enrollment_id)
        try:
            if not await self.runs.claim(e.id):
                raise InFlight(e.enrollment_id)
            try:
                return await self._submit(e, form, chosen, modes, actor)
            except Exception:
                log.exception("submission crashed for %s", e.enrollment_id)
                await self._finish(e, "failed", chosen, None, [self._reason(
                    "SUBMISSION_FAILED", "The submission stopped unexpectedly; it can be tried again.")],
                    actor, ("submission.failed", {"path": chosen, "code": "CRASHED"}))
                raise
        finally:
            await self.shared.delete(lock)

    async def _submit(self, e: Enrollment, form: FormSpec, path: str, modes: TestModes, actor: str) -> Summary:
        payload = dict(e.mapped_payload or {})
        summary = Summary(e.enrollment_id, "submitting", path)
        resolver = Resolver(form.id, await self.runs.locators(form.id))

        result = await self._already_there(e, form, payload, path, modes, actor, "before sending")
        last: SubmitError | None = None
        attempt = 0
        while result is None and attempt < self.max_attempts:
            attempt += 1
            if path == "api" and attempt == self.max_attempts and attempt > 1 and form.url_path and \
                    last is not None and last.code == UNAVAILABLE:
                path = "browser"   # the API kept failing: one try through the web form
            try:
                run_id = await self.runs.start(e.id, path, modes.as_dict(), actor)
            except RunInProgress:
                raise InFlight(e.enrollment_id) from None
            try:
                if path == "api":
                    result = await self.api.submit(form, payload, modes)
                else:
                    result = await self.browser.submit(form, payload, modes, resolver)
            except SubmitError as err:
                last = err
                await self.runs.finish(run_id, "halted" if err.code == HUMAN_CHECK else "failed",
                                       error_code=err.code, error_detail=mask_text(err.detail)[:500],
                                       steps=err.steps, shots=err.shots)
                if not err.retryable or attempt >= self.max_attempts:
                    break
                await self.sleep(self.backoff_s * 2 ** (attempt - 1) + random.uniform(0, 0.5))  # noqa: S311
                result = await self._already_there(e, form, payload, path, modes, actor, "after an unclear failure")
                continue
            await self.runs.finish(run_id, "succeeded", confirmation_ref=result.confirmation_ref,
                                   steps=result.steps, shots=result.shots)

        summary.attempts, summary.path = attempt, path
        if resolver.learned or resolver.used:
            await self.runs.learn(form.id, resolver.learned, resolver.heals, resolver.used)
        summary.healed = [{"target": h.target, "from": h.old, "to": h.new} for h in resolver.heals]
        if resolver.heals:
            await self.enrollments.audit(e, "submitter", "locator.healed", {"healed": summary.healed})

        if result is not None:
            return await self._succeeded(e, form, payload, path, result, summary, actor)
        assert last is not None
        summary.error = {"code": last.code, "detail": last.detail}
        if last.code in TO_A_PERSON:
            labels = {f.name: f.label for f in form.fields}
            reasons = [self._reason("PORTAL_REJECTED", f"{labels.get(fe['field'], fe['field'])}: the portal said: "
                                    f"{mask_text(fe['message'])}", fe["field"])
                       for fe in last.field_errors] if last.code == REJECTED else []
            if last.code == HUMAN_CHECK:
                reasons.append(self._reason("HUMAN_CHECK_REQUIRED", "The portal asked for a security check. Finish "
                                            "this submission by hand, or try again later."))
            if not reasons:
                reasons.append(self._reason("SUBMISSION_FAILED", f"Submission stopped: {last.detail}."))
            status = "needs_review"
        else:
            reasons = [self._reason("SUBMISSION_FAILED", f"Submission failed after {attempt} attempt(s): "
                                    f"{last.detail}. It can be tried again.")]
            status = "failed"
        summary.status = status
        await self._finish(e, status, path, None, reasons, actor,
                           ("submission.failed", {"path": path, "code": last.code, "attempts": attempt}))
        await self._alert(f"Enrollment {e.enrollment_id} ({form.portal}) was not submitted: "
                          f"{last.code.replace('_', ' ').lower()} after {attempt} attempt(s). It is "
                          f"{'waiting for a person' if status == 'needs_review' else 'marked failed'}.")
        return summary

    async def _alert(self, text: str) -> None:
        """Tell the operators in chat. Best effort: an alert that cannot be sent never changes the outcome.
        The text holds the enrollment ID, portal and error code only, never personal data."""
        if self.alert_url:
            await post_alert(self.alert_url, text)

    async def _already_there(self, e: Enrollment, form: FormSpec, payload: dict[str, Any], path: str,
                             modes: TestModes, actor: str, when: str) -> AttemptResult | None:
        try:
            found = await self.api.find(form, payload)
        except SubmitError:
            return None
        if found is None:
            return None
        ref, record = found
        run_id = await self.runs.start(e.id, path, modes.as_dict(), actor)
        await self.runs.finish(run_id, "succeeded", confirmation_ref=ref,
                               steps=[{"lookup": f"found at the portal {when}"}])
        return AttemptResult(confirmation_ref=ref, portal_record=record, adopted=True,
                             notes=[f"The portal already had this applicant ({when}); nothing was sent again."])

    async def _succeeded(self, e: Enrollment, form: FormSpec, payload: dict[str, Any], path: str,
                         result: AttemptResult, summary: Summary, actor: str) -> Summary:
        record = await self.api.get(form, result.confirmation_ref) or result.portal_record
        reasons = []
        if record is None:
            summary.readback = "unavailable"
            reasons.append(self._reason("READBACK_UNAVAILABLE", "Submitted, but the portal's record could not be read "
                                        "back to check it.", severity="info"))
        else:
            wrong = mismatches(form, payload, record)
            summary.readback = "mismatch" if wrong else "matched"
            for name in wrong:
                reasons.append(self._reason("READBACK_MISMATCH", f"{form.field(name).label}: the portal's record "
                                            "differs from what was sent. Check it at the portal.", name))
        if result.adopted:
            reasons.append(self._reason("ADOPTED_EXISTING", " ".join(result.notes), severity="info"))
        summary.status, summary.confirmation_ref, summary.adopted = "submitted", result.confirmation_ref, result.adopted
        await self._finish(e, "submitted", path, result.confirmation_ref, reasons, actor,
                           ("submission.succeeded", {"path": path, "confirmation_ref": result.confirmation_ref,
                                                     "attempts": summary.attempts, "adopted": result.adopted,
                                                     "readback": summary.readback}))
        return summary

    @staticmethod
    def _reason(code: str, message: str, field: str | None = None, severity: str = "review") -> dict[str, Any]:
        return {"code": code, "field": field, "message": message, "severity": severity}

    async def _finish(self, e: Enrollment, status: str, path: str | None, ref: str | None,
                      reasons: list[dict[str, Any]], actor: str, event: tuple[str, dict[str, Any]]) -> None:
        kept = [r for r in e.issues if r.get("code") not in SUBMISSION_CODES]
        if status == "submitted":   # the sign-off has happened: the note no longer applies
            kept = [r for r in kept if r.get("code") != "SIGNOFF_REQUIRED"]
        await self.enrollments.set_submission(e, status=status, path=path, ref=ref, reasons=reasons + kept,
                                              actor=actor, event=event)
