"""Real submissions: Chromium (Playwright) against the two practice portals, end to end through the engine's API.

Needs the portals running (cd frontend && npm run build && PORTAL_API_KEY=dev-portal-key npx next start -p 3100)
and TEST_PORTAL_URL=http://localhost:3100. Skipped otherwise.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.submit.browser import BrowserSubmitter
from app.submit.portal_api import PortalAPI
from tests.conftest import academy_adult, academy_minor, club_adult, needs_db

PORTAL = os.environ.get("TEST_PORTAL_URL", "")
pytestmark = [needs_db, pytest.mark.skipif(not PORTAL, reason="set TEST_PORTAL_URL to run against the portals")]
SOON = (date.today() + timedelta(days=12)).isoformat()


async def _no_wait(_: float) -> None:
    return None


@pytest.fixture
def live(client: TestClient) -> TestClient:
    s = client.app.state.submitter  # type: ignore[attr-defined]
    s.api = PortalAPI(PORTAL, os.environ.get("TEST_PORTAL_KEY", "dev-portal-key"))
    s.browser = BrowserSubmitter(PORTAL)
    s.sleep = _no_wait
    return client


def unique(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex[:8]}@example.com"


def riverside(client: TestClient, record: dict[str, Any]) -> str:
    body = client.post("/api/enrollments", json={"target_form": "riverside-enrollment", "record": record}).json()
    assert body["status"] == "approved", body["reasons"]
    return body["enrollment_id"]


def harbour(client: TestClient, **over: Any) -> str:
    body = client.post("/api/enrollments", json={"target_form": "harbour-membership", "record": club_adult(
        start_date=SOON, email=unique("sofia"), **over)}).json()
    client.post(f"/api/enrollments/{body['enrollment_id']}/approve", json={})
    return body["enrollment_id"]


def submit(client: TestClient, eid: str, **body: Any) -> dict[str, Any]:
    res = client.post(f"/api/enrollments/{eid}/submit", json={"wait": True, **body})
    assert res.status_code == 200, res.text
    return res.json()


def test_riverside_wizard_in_a_browser(live: TestClient) -> None:
    eid = riverside(live, academy_adult(email=unique("amara")))
    out = submit(live, eid)
    assert (out["status"], out["path"], out["readback"]) == ("submitted", "browser", "matched"), out
    assert out["confirmation_ref"].startswith("RVA-")
    run = live.get(f"/api/enrollments/{eid}/runs").json()[0]
    assert [s["result"] for s in run["steps"]] == ["moved", "moved", "moved", "confirmation"]
    assert run["steps"][0]["filled"] == ["first_name", "last_name", "date_of_birth", "email", "phone"]
    assert len(run["screenshots"]) == 5
    shot = live.get(f"/api/runs/{run['run_id']}/screenshots/{run['screenshots'][-1]['id']}")
    assert shot.content[:2] == b"\xff\xd8"


def test_riverside_minor_gets_the_guardian_step(live: TestClient) -> None:
    eid = riverside(live, academy_minor(email=unique("leo")))
    out = submit(live, eid)
    assert out["status"] == "submitted" and out["readback"] == "matched"
    steps = live.get(f"/api/enrollments/{eid}/runs").json()[0]["steps"]
    assert "guardian_name" in steps[1]["filled"]


def test_a_drifted_page_heals_and_the_next_run_uses_what_was_learned(live: TestClient) -> None:
    first = submit(live, riverside(live, academy_adult(email=unique("drift"))), variant="b")
    assert first["status"] == "submitted" and first["readback"] == "matched"
    healed = {h["target"] for h in first["healed"]}
    assert {"first_name", "program", "button:next", "button:submit"} <= healed
    again = submit(live, riverside(live, academy_adult(email=unique("drift2"))), variant="b")
    assert again["status"] == "submitted" and again["healed"] == []


def test_a_flaky_portal_is_retried(live: TestClient) -> None:
    out = submit(live, riverside(live, academy_adult(email=unique("flaky"))), chaos="flaky")
    assert out["status"] == "submitted" and out["attempts"] == 2


def test_a_lost_reply_is_adopted_not_resent(live: TestClient) -> None:
    out = submit(live, riverside(live, academy_adult(email=unique("lost"))), chaos="lost")
    assert out["status"] == "submitted" and out["adopted"] is True


def test_a_captcha_stops_the_bot(live: TestClient) -> None:
    eid = riverside(live, academy_adult(email=unique("bot")))
    out = submit(live, eid, chaos="captcha")
    assert out["status"] == "needs_review" and out["error"]["code"] == "HUMAN_CHECK_REQUIRED"
    assert live.get(f"/api/enrollments/{eid}/runs").json()[0]["status"] == "halted"


def test_harbour_by_api_and_by_browser(live: TestClient) -> None:
    by_api = submit(live, harbour(live, membership_type="family", family_members=4))
    assert (by_api["path"], by_api["status"], by_api["readback"]) == ("api", "submitted", "matched")
    by_browser = submit(live, harbour(live, membership_type="student", student_id="UOL-482913"), path="browser")
    assert (by_browser["path"], by_browser["status"], by_browser["readback"]) == ("browser", "submitted", "matched")


def test_harbour_drifted_page_through_the_browser(live: TestClient) -> None:
    out = submit(live, harbour(live), path="browser", variant="b")
    assert out["status"] == "submitted" and out["readback"] == "matched" and out["healed"]
