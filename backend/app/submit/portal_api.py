"""The portals' HTTP APIs: submitting a record (where the portal has a submission API) and reading records back.

Reading back is what makes retries safe: before sending again after an unclear failure, and before the first send
when an earlier run may have got through, we ask the portal whether it already has this applicant.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.forms.base import FormSpec
from app.submit.base import AUTH, REJECTED, UNAVAILABLE, AttemptResult, SubmitError, TestModes
from app.submit.compare import mismatches

TIMEOUT = httpx.Timeout(20.0, connect=5.0)


def _record(body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Both portals' shapes: {ref, application} and {member_id, member}."""
    ref = str(body.get("ref") or body.get("member_id") or "")
    data = body.get("application") or body.get("member") or {}
    return ref, data if isinstance(data, dict) else {}


class PortalAPI:
    def __init__(self, base_url: str, api_key: str, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.transport = transport   # tests pass a mock transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=TIMEOUT, transport=self.transport,
                                 headers={"x-portal-key": self.api_key})

    async def submit(self, form: FormSpec, payload: dict[str, Any], modes: TestModes) -> AttemptResult:
        headers = {"x-portal-chaos": modes.chaos} if modes.chaos else {}
        try:
            async with self._client() as client:
                res = await client.post(form.api_path, json=payload, headers=headers)
        except httpx.TimeoutException:
            raise SubmitError(UNAVAILABLE, "the portal did not answer in time", retryable=True) from None
        except httpx.HTTPError:
            raise SubmitError(UNAVAILABLE, "could not connect to the portal", retryable=True) from None
        body = _json(res)
        if res.status_code == 201:
            ref, data = _record(body)
            return AttemptResult(confirmation_ref=ref, portal_record=data, steps=[{"api": "POST", "status": 201}])
        if res.status_code == 409 and (body.get("member_id") or body.get("ref")):
            ref = str(body.get("member_id") or body.get("ref"))
            return AttemptResult(confirmation_ref=ref, adopted=True, steps=[{"api": "POST", "status": 409}],
                                 notes=["The portal already had this applicant; the existing record was kept."])
        if res.status_code == 422:
            errors = [{"field": str(e.get("field")), "message": str(e.get("message"))}
                      for e in body.get("errors", []) if isinstance(e, dict)]
            raise SubmitError(REJECTED, f"the portal refused {len(errors)} field(s)", retryable=False,
                              field_errors=errors)
        if res.status_code in (401, 403):
            raise SubmitError(AUTH, "the portal refused the API key", retryable=False)
        if res.status_code >= 500 or res.status_code == 429:
            raise SubmitError(UNAVAILABLE, f"the portal answered {res.status_code}", retryable=True)
        raise SubmitError(REJECTED, f"the portal answered {res.status_code}", retryable=False)

    async def get(self, form: FormSpec, ref: str) -> dict[str, Any] | None:
        if not form.lookup_path:
            return None
        try:
            async with self._client() as client:
                res = await client.get(f"{form.lookup_path}/{ref}")
        except httpx.HTTPError:
            return None
        return _record(_json(res))[1] if res.status_code == 200 else None

    async def find(self, form: FormSpec, payload: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        """A record at the portal for this applicant that matches what we would send, if there is one."""
        email = payload.get("email")
        if not form.lookup_path or not email:
            return None
        try:
            async with self._client() as client:
                res = await client.get(form.lookup_path, params={"email": str(email)})
        except httpx.HTTPError:
            raise SubmitError(UNAVAILABLE, "could not check the portal for an earlier submission",
                              retryable=True) from None
        if res.status_code >= 500:
            raise SubmitError(UNAVAILABLE, "could not check the portal for an earlier submission", retryable=True)
        if res.status_code != 200:
            return None
        body = _json(res)
        for item in body.get("applications") or body.get("members") or []:
            ref, data = _record(item)
            if ref and not mismatches(form, payload, data):
                return ref, data
        return None


def _json(res: httpx.Response) -> dict[str, Any]:
    try:
        body = res.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
