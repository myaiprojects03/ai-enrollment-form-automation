"""Production settings, serverless dispatch, approval acceptance, retention, key rotation, response headers."""
from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.maintenance import purge, rotate
from app.security.crypto import FieldCipher, new_key
from app.submit import browser as browser_module
from app.submit.base import SubmitError, TestModes
from app.submit.browser import BrowserSubmitter
from app.submit.locators import Resolver
from tests.conftest import TEST_DB, academy_adult, needs_db
from tests.test_pipeline import raw
from tests.test_submit import Portal, harbour, setup


def test_production_settings_are_checked() -> None:
    weak = Settings(app_env="production", operator_token="short", session_secret="", portal_api_key="dev-portal-key",
                    redis_url="", submit_mode="dispatch")
    problems = " ".join(weak.production_problems())
    for needle in ("OPERATOR_TOKEN", "SESSION_SECRET", "PORTAL_API_KEY", "REDIS_URL", "GITHUB_DISPATCH_REPO"):
        assert needle in problems
    good = Settings(app_env="production", operator_token="x" * 32, session_secret="y" * 32, portal_api_key="k" * 24,
                    redis_url="rediss://example", submit_mode="inline")
    assert good.production_problems() == []


def test_without_playwright_the_browser_path_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.forms.registry import get_form
    monkeypatch.setattr(browser_module, "async_playwright", None)
    with pytest.raises(SubmitError) as err:
        asyncio.run(BrowserSubmitter("http://x").submit(get_form("riverside-enrollment"), {}, TestModes(),
                                                        Resolver("riverside-enrollment")))
    assert err.value.code == "BROWSER_UNAVAILABLE" and not err.value.retryable


@needs_db
def test_api_answers_carry_safety_headers(client: TestClient) -> None:
    res = client.get("/api/forms")
    assert res.headers["cache-control"] == "no-store" and res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"


@needs_db
def test_approval_records_which_points_the_reviewer_accepted(client: TestClient) -> None:
    record = academy_adult(date_of_birth="03/04/1999")
    eid = client.post("/api/enrollments", json={"target_form": "riverside-enrollment", "record": record}).json()[
        "enrollment_id"]
    client.post(f"/api/enrollments/{eid}/approve", json={"note": "Checked the date with the applicant"})
    detail = client.get(f"/api/enrollments/{eid}").json()
    low = next(r for r in detail["reasons"] if r["code"] == "LOW_CONFIDENCE")
    assert low["accepted_by"] == "operator"
    approved = next(a for a in detail["audit"] if a["action"] == "enrollment.approved")
    assert approved["details"]["accepted"] == ["LOW_CONFIDENCE"]


@needs_db
def test_serverless_mode_hands_web_form_submissions_to_the_worker(client: TestClient,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_trigger(repo: str, token: str) -> bool:
        calls.append((repo, token))
        return True

    from app.api import submissions
    monkeypatch.setattr(submissions, "trigger_worker", fake_trigger)
    s = get_settings()
    monkeypatch.setattr(s, "submit_mode", "dispatch")
    monkeypatch.setattr(s, "github_dispatch_repo", "me/enrollment-automation")
    monkeypatch.setattr(s, "github_dispatch_token", "t")
    setup(client, Portal())
    rid = client.post("/api/enrollments", json={"target_form": "riverside-enrollment",
                                                "record": academy_adult()}).json()["enrollment_id"]
    res = client.post(f"/api/enrollments/{rid}/submit", json={})
    assert res.status_code == 202 and res.json()["via"] == "worker" and calls == [("me/enrollment-automation", "t")]
    assert client.get(f"/api/enrollments/{rid}").json()["status"] == "approved"   # waiting for the worker
    # The club has an API: that runs straight away, even serverless.
    out = client.post(f"/api/enrollments/{harbour(client)}/submit", json={})
    assert out.status_code == 200 and out.json()["status"] == "submitted" and len(calls) == 1


async def _cipher_pool() -> Any:
    from app.db.migrations import connect
    return await connect(TEST_DB)


@needs_db
def test_retention_erases_personal_data_and_keeps_the_trail(client: TestClient) -> None:
    eid = client.post("/api/enrollments", json={"target_form": "riverside-enrollment",
                                                "record": academy_adult(consent_terms="no")}).json()["enrollment_id"]
    client.post(f"/api/enrollments/{eid}/reject", json={"note": "withdrew"})
    raw("UPDATE enrollments SET updated_at = now() - interval '100 days' WHERE enrollment_id = $1", eid)
    cipher = client.app.state.enrollments.cipher  # type: ignore[attr-defined]

    async def go() -> list[str]:
        pool = await _cipher_pool()
        try:
            return await purge(pool, cipher, 90)
        finally:
            await pool.close()

    assert asyncio.run(go()) == [eid]
    assert asyncio.run(go()) == []            # once only
    shown = client.get(f"/api/enrollments/{eid}", params={"reveal": "true"}).json()
    assert shown["source_record"] == {} and shown["mapped_payload"] is None
    assert all("value" in f and f["value"] is None for f in shown["fields"])
    assert shown["status"] == "rejected" and shown["reasons"]
    assert "personal_data.purged" in [a["action"] for a in shown["audit"]]


@needs_db
def test_key_rotation_reseals_everything_under_the_new_key(client: TestClient) -> None:
    eid = client.post("/api/enrollments", json={"target_form": "riverside-enrollment",
                                                "record": academy_adult()}).json()["enrollment_id"]
    rotated = FieldCipher.from_setting(f"{new_key()},{os.environ['ENCRYPTION_KEYS']}")   # a new key goes first

    async def go() -> dict[str, int]:
        pool = await _cipher_pool()
        try:
            return await rotate(pool, rotated)
        finally:
            await pool.close()

    first = asyncio.run(go())
    assert first["enrollments"] == 1 and first["field_mappings"] > 10
    assert asyncio.run(go()) == {"enrollments": 0, "field_mappings": 0, "screenshots": 0}
    client.app.state.enrollments.cipher = rotated  # type: ignore[attr-defined]
    shown = client.get(f"/api/enrollments/{eid}", params={"reveal": "true"}).json()
    assert shown["source_record"]["email"] == "amara.okafor@example.com"
