"""The submission runner against Postgres, with the portal faked: retries, lost replies, refusals, halts, locks,
approval, screenshots and learned locators. The real browser runs in test_submit_e2e.py."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.forms.registry import get_form
from app.submit.base import HUMAN_CHECK, NOT_SET, UNAVAILABLE, AttemptResult, Shot, SubmitError, TestModes
from app.submit.compare import mismatches
from app.submit.locators import Heal, Learned, Resolver
from app.submit.portal_api import PortalAPI
from tests.conftest import academy_adult, club_adult, needs_db
from tests.test_pipeline import raw

SOON = (date.today() + timedelta(days=10)).isoformat()
JPEG = b"\xff\xd8\xff\xe0fake-screenshot-of-amara-okafor"


async def _no_wait(_: float) -> None:
    return None


class Portal:
    """A fake portal API: scripted answers to POST, and a store that lookups read."""

    def __init__(self, answers: list[int] | None = None, saves_on: set[int] | None = None):
        self.answers = answers or [201]
        self.saves_on = saves_on if saves_on is not None else {201}
        self.stored: dict[str, dict[str, Any]] = {}
        self.posts = 0

    def handler(self, req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            status = self.answers[min(self.posts, len(self.answers) - 1)]
            self.posts += 1
            body = json.loads(req.content)
            if status in self.saves_on:
                self.stored[f"HSC-{100000 + len(self.stored)}"] = body
            if status == 201:
                ref = list(self.stored)[-1]
                return httpx.Response(201, json={"member_id": ref, "member": body})
            if status == 422:
                return httpx.Response(422, json={"errors": [{"field": "phone", "message": "Use a UK number."}]})
            return httpx.Response(status, json={"error": "nope"})
        if req.url.params.get("email"):
            found = [{"member_id": r, "member": d} for r, d in self.stored.items()
                     if d.get("email") == req.url.params["email"]]
            return httpx.Response(200, json={"members": found})
        ref = req.url.path.rsplit("/", 1)[-1]
        if ref in self.stored:
            return httpx.Response(200, json={"member_id": ref, "member": self.stored[ref]})
        return httpx.Response(404, json={})


class FakeBrowser:
    def __init__(self, act: Callable[[dict[str, Any], Resolver], AttemptResult]):
        self.act = act
        self.calls = 0

    async def submit(self, form: Any, payload: dict[str, Any], modes: TestModes, resolver: Resolver) -> AttemptResult:
        self.calls += 1
        return self.act(payload, resolver)


def fail_browser(code: str, retryable: bool = False) -> Callable[[dict[str, Any], Resolver], AttemptResult]:
    def act(payload: dict[str, Any], resolver: Resolver) -> AttemptResult:
        err = SubmitError(code, "scripted failure", retryable=retryable)
        err.shots = [Shot("when it went wrong", JPEG)]
        raise err
    return act


def setup(client: TestClient, portal: Portal, browser: FakeBrowser | None = None) -> None:
    s = client.app.state.submitter  # type: ignore[attr-defined]
    s.api = PortalAPI("http://portal.test", "k", transport=httpx.MockTransport(portal.handler))
    s.browser = browser or FakeBrowser(fail_browser(UNAVAILABLE))
    s.sleep = _no_wait


def harbour(client: TestClient, **over: Any) -> str:
    """A Harbour member, mapped (PASS, waiting for sign-off) and approved."""
    body = client.post("/api/enrollments", json={"target_form": "harbour-membership",
                                                 "record": club_adult(start_date=SOON, **over)}).json()
    eid = body["enrollment_id"]
    assert client.post(f"/api/enrollments/{eid}/approve", json={}).json()["status"] == "approved"
    return eid


def submit(client: TestClient, eid: str, **body: Any) -> dict[str, Any]:
    res = client.post(f"/api/enrollments/{eid}/submit", json={"wait": True, **body})
    assert res.status_code == 200, res.text
    return res.json()


def runs(client: TestClient, eid: str) -> list[dict[str, Any]]:
    return client.get(f"/api/enrollments/{eid}/runs").json()


pytestmark = needs_db


def test_api_submission_is_read_back_and_matches(client: TestClient) -> None:
    portal = Portal()
    setup(client, portal)
    eid = harbour(client)
    out = submit(client, eid)
    assert (out["status"], out["path"], out["readback"], out["attempts"]) == ("submitted", "api", "matched", 1)
    assert out["confirmation_ref"] == "HSC-100000"
    detail = client.get(f"/api/enrollments/{eid}").json()
    assert detail["confirmation_ref"] == "HSC-100000" and detail["submit_path"] == "api"
    assert "submission.succeeded" in [a["action"] for a in detail["audit"]]
    assert submit(client, eid)["already_submitted"] is True and portal.posts == 1   # never sent twice


def test_a_temporary_failure_is_retried(client: TestClient) -> None:
    portal = Portal(answers=[503, 201])
    setup(client, portal)
    out = submit(client, harbour(client))
    assert out["status"] == "submitted" and out["attempts"] == 2 and portal.posts == 2
    assert [r["status"] for r in runs(client, out["enrollment_id"])] == ["failed", "succeeded"]


def test_a_lost_reply_is_found_and_not_sent_again(client: TestClient) -> None:
    portal = Portal(answers=[504, 201], saves_on={504, 201})   # saved, but the reply never arrived
    setup(client, portal)
    out = submit(client, harbour(client))
    assert out["status"] == "submitted" and out["adopted"] is True
    assert portal.posts == 1 and len(portal.stored) == 1
    steps = [r["steps"] for r in runs(client, out["enrollment_id"])]
    assert steps[-1] == [{"lookup": "found at the portal after an unclear failure"}]


def test_an_earlier_submission_is_found_before_sending(client: TestClient) -> None:
    portal = Portal()
    setup(client, portal)
    eid = harbour(client)
    payload = client.get(f"/api/enrollments/{eid}", params={"reveal": "true"}).json()["mapped_payload"]
    portal.stored["HSC-424242"] = payload
    out = submit(client, eid)
    assert out["confirmation_ref"] == "HSC-424242" and out["adopted"] and portal.posts == 0


def test_a_refused_field_goes_back_to_a_person(client: TestClient) -> None:
    portal = Portal(answers=[422])
    setup(client, portal)
    eid = harbour(client)
    out = submit(client, eid)
    assert out["status"] == "needs_review" and out["error"]["code"] == "PORTAL_REJECTED" and portal.posts == 1
    reasons = client.get(f"/api/enrollments/{eid}").json()["reasons"]
    rejected = [r for r in reasons if r["code"] == "PORTAL_REJECTED"]
    assert rejected == [{"code": "PORTAL_REJECTED", "field": "phone", "severity": "review",
                         "message": "Phone: the portal said: Use a UK number."}]
    # Fixed and approved again, it goes through; the old submission reasons are cleared.
    portal.answers = [201]
    client.patch(f"/api/enrollments/{eid}/fields", json={"changes": {"phone": "07800 345679"}})
    assert client.post(f"/api/enrollments/{eid}/approve", json={}).json()["status"] == "approved"
    assert submit(client, eid)["status"] == "submitted"
    codes = {r["code"] for r in client.get(f"/api/enrollments/{eid}").json()["reasons"]}
    assert "PORTAL_REJECTED" not in codes


def test_a_refused_api_key_is_not_retried(client: TestClient) -> None:
    portal = Portal(answers=[401])
    setup(client, portal)
    out = submit(client, harbour(client))
    assert out["status"] == "failed" and out["error"]["code"] == "PORTAL_AUTH_FAILED" and portal.posts == 1


def test_when_the_api_keeps_failing_the_last_try_uses_the_browser(client: TestClient) -> None:
    portal = Portal(answers=[503])
    browser = FakeBrowser(lambda payload, r: AttemptResult("HSC-777777", portal_record=payload,
                                                           shots=[Shot("confirmation", JPEG)]))
    setup(client, portal, browser)
    out = submit(client, harbour(client))
    assert (out["status"], out["path"], out["attempts"]) == ("submitted", "browser", 3)
    assert portal.posts == 2 and browser.calls == 1
    assert [r["path"] for r in runs(client, out["enrollment_id"])] == ["api", "api", "browser"]


def test_a_security_check_halts_and_waits_for_a_person(client: TestClient) -> None:
    browser = FakeBrowser(fail_browser(HUMAN_CHECK))
    setup(client, Portal(), browser)
    eid = client.post("/api/enrollments", json={"target_form": "riverside-enrollment",
                                                "record": academy_adult()}).json()["enrollment_id"]
    out = submit(client, eid)
    assert out["status"] == "needs_review" and browser.calls == 1
    run = runs(client, eid)[0]
    assert run["status"] == "halted" and run["error_code"] == HUMAN_CHECK and len(run["screenshots"]) == 1


def test_a_value_that_will_not_stick_is_retried_then_sent_to_a_person(client: TestClient) -> None:
    browser = FakeBrowser(fail_browser(NOT_SET, retryable=True))
    setup(client, Portal(), browser)
    eid = client.post("/api/enrollments", json={"target_form": "riverside-enrollment",
                                                "record": academy_adult()}).json()["enrollment_id"]
    out = submit(client, eid)
    assert browser.calls == 3 and out["status"] == "needs_review"


def test_screenshots_are_encrypted_and_viewing_one_is_audited(client: TestClient) -> None:
    setup(client, Portal(), FakeBrowser(fail_browser(HUMAN_CHECK)))
    eid = client.post("/api/enrollments", json={"target_form": "riverside-enrollment",
                                                "record": academy_adult()}).json()["enrollment_id"]
    submit(client, eid)
    stored = bytes(raw("SELECT content FROM run_artifacts")[0]["content"])
    assert b"amara" not in stored and b"\xff\xd8" not in stored
    run = runs(client, eid)[0]
    res = client.get(f"/api/runs/{run['run_id']}/screenshots/{run['screenshots'][0]['id']}")
    assert res.status_code == 200 and res.content == JPEG and res.headers["content-type"] == "image/jpeg"
    assert "screenshot.viewed" in [a["action"] for a in client.get(f"/api/enrollments/{eid}").json()["audit"]]


def test_healed_locators_are_learned_and_audited(client: TestClient) -> None:
    def act(payload: dict[str, Any], resolver: Resolver) -> AttemptResult:
        resolver.heals.append(Heal("first_name", "testid:ra-first-name", "label:Given name"))
        resolver.learned["first_name"] = Learned("label", "Given name")
        resolver.used["first_name"] = "label:Given name"
        return AttemptResult("RVA-2026-ABCDE", portal_record=payload)
    setup(client, Portal(), FakeBrowser(act))
    eid = client.post("/api/enrollments", json={"target_form": "riverside-enrollment",
                                                "record": academy_adult()}).json()["enrollment_id"]
    out = submit(client, eid)
    assert out["healed"] == [{"target": "first_name", "from": "testid:ra-first-name", "to": "label:Given name"}]
    row = raw("SELECT strategy, arg, healed_at FROM locator_cache WHERE target = 'first_name'")[0]
    assert (row["strategy"], row["arg"]) == ("label", "Given name") and row["healed_at"] is not None
    assert "locator.healed" in [a["action"] for a in client.get(f"/api/enrollments/{eid}").json()["audit"]]


def test_only_approved_enrollments_are_submitted(client: TestClient) -> None:
    setup(client, Portal())
    eid = client.post("/api/enrollments", json={"target_form": "harbour-membership",
                                                "record": club_adult(start_date=SOON)}).json()["enrollment_id"]
    res = client.post(f"/api/enrollments/{eid}/submit", json={"wait": True})
    assert res.status_code == 409 and "needs_review" in res.json()["detail"]


def test_a_second_submit_while_one_is_running_is_refused(client: TestClient) -> None:
    setup(client, Portal())
    eid = harbour(client)
    e = asyncio.run(_enrollment(eid))
    asyncio.run(client.app.state.shared.add(f"submit:{e}", "someone", 60))  # type: ignore[attr-defined]
    res = client.post(f"/api/enrollments/{eid}/submit", json={"wait": True})
    assert res.status_code == 409 and "right now" in res.json()["detail"]


async def _enrollment(eid: str) -> Any:
    from tests.test_pipeline import _raw
    return (await _raw("SELECT id FROM enrollments WHERE enrollment_id = $1", eid))[0]["id"]


def test_approval_is_refused_while_a_blocking_problem_is_open(client: TestClient) -> None:
    eid = client.post("/api/enrollments", json={"target_form": "riverside-enrollment",
                                                "record": academy_adult(consent_terms="no")}).json()["enrollment_id"]
    assert client.post(f"/api/enrollments/{eid}/approve", json={}).status_code == 409
    rejected = client.post(f"/api/enrollments/{eid}/reject", json={"note": "Applicant withdrew by phone"}).json()
    assert rejected["status"] == "rejected"
    assert client.patch(f"/api/enrollments/{eid}/fields", json={"changes": {"city": "York"}}).status_code == 409


def test_test_modes_can_be_switched_off(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    setup(client, Portal())
    eid = harbour(client)
    monkeypatch.setattr(get_settings(), "allow_test_modes", False)
    res = client.post(f"/api/enrollments/{eid}/submit", json={"wait": True, "chaos": "flaky"})
    assert res.status_code == 403


def test_background_submission(client: TestClient) -> None:
    setup(client, Portal())
    eid = harbour(client)
    res = client.post(f"/api/enrollments/{eid}/submit", json={})
    assert res.status_code == 202 and res.json()["queued"] is True
    for _ in range(50):
        if client.get(f"/api/enrollments/{eid}").json()["status"] == "submitted":
            break
        asyncio.run(asyncio.sleep(0.05))
    assert client.get(f"/api/enrollments/{eid}").json()["status"] == "submitted"


def test_interrupted_runs_are_recovered(client: TestClient) -> None:
    setup(client, Portal())
    eid = harbour(client)
    e = asyncio.run(_enrollment(eid))
    raw("UPDATE enrollments SET status = 'submitting', updated_at = now() - interval '1 hour' WHERE id = $1", e)
    raw("INSERT INTO submission_runs (enrollment_id, attempt, path, started_at) "
        "VALUES ($1, 1, 'api', now() - interval '1 hour')", e)
    recovered = asyncio.run(_recover(client))
    assert e in recovered
    assert client.get(f"/api/enrollments/{eid}").json()["status"] == "approved"
    assert runs(client, eid)[0]["error_code"] == "INTERRUPTED"


async def _recover(client: TestClient) -> list[Any]:
    from app.db.migrations import connect
    from app.submit.store import RunStore
    from tests.conftest import TEST_DB
    pool = await connect(TEST_DB)
    try:
        return await RunStore(pool, client.app.state.runs.cipher).interrupted(600)  # type: ignore[attr-defined]
    finally:
        await pool.close()


def test_comparison_uses_each_types_idea_of_equal() -> None:
    form = get_form("harbour-membership")
    ours = {"full_name": "Sofia Marin", "phone": "+447800345678", "interests": ["yoga", "gym"], "family_members": 3,
            "accept_terms": True, "email": "sofia@example.com"}
    theirs = {"full_name": " sofia  marin", "phone": "07800 345678", "interests": ["gym", "yoga"],
              "family_members": "3", "accept_terms": True, "email": "SOFIA@example.com", "how_heard": None}
    assert mismatches(form, ours, theirs) == []
    assert mismatches(form, ours, {**theirs, "phone": "07800 000000", "interests": ["gym"]}) == ["phone", "interests"]
