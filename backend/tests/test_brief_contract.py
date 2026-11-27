"""The brief's exact contracts: the mapper's structured payload, the run history view, operator alerts."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import academy_adult, needs_db
from tests.test_submit import Portal, harbour, setup, submit

pytestmark = needs_db


def test_mapping_payload_has_the_four_parts(client: TestClient) -> None:
    record = {**academy_adult(), "Mobile": "07400 999888", "Name": None}
    del record["consent_terms"]
    eid = client.post("/api/enrollments", json={"target_form": "riverside-enrollment", "record": record}).json()[
        "enrollment_id"]
    out = client.get(f"/api/enrollments/{eid}/mapping").json()
    assert set(out) == {"enrollment_id", "target_form", "schema_valid", "mapped_fields", "confidence_scores",
                        "unmapped_or_ambiguous_fields", "assumptions_made"}
    assert out["mapped_fields"]["phone"] == "+447911123456" and out["confidence_scores"]["phone"] == 0.5
    assert out["unmapped_or_ambiguous_fields"] == ["consent_terms", "phone"]   # missing, and two candidates
    assert any(a.startswith("Mobile number: Both 'phone' and 'Mobile'") for a in out["assumptions_made"])
    assert out["schema_valid"] is False                                    # consent is missing
    assert "guardian_name" not in out["unmapped_or_ambiguous_fields"]      # not needed for an adult
    actions = [a["action"] for a in client.get(f"/api/enrollments/{eid}").json()["audit"]]
    assert "personal_data.viewed" in actions


def test_run_history_lists_every_attempt_with_retries(client: TestClient) -> None:
    setup(client, Portal(answers=[503, 201]))
    eid = harbour(client)
    submit(client, eid)
    runs = client.get("/api/runs").json()
    assert [(r["attempt"], r["status"], r["retries_before"]) for r in runs] == [(2, "succeeded", 1), (1, "failed", 0)]
    assert runs[0]["confirmation_ref"] and runs[0]["enrollment_id"] == eid and runs[1]["error_code"]
    assert [r["attempt"] for r in client.get("/api/runs", params={"status": "failed"}).json()] == [1]
    assert client.get("/api/runs", params={"form": "riverside-enrollment"}).json() == []
    assert len(client.get("/api/runs", params={"q": eid.lower()}).json()) == 2


def test_operators_are_alerted_when_a_submission_fails(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []

    async def fake_post(url: str, text: str) -> None:
        sent.append({"url": url, "text": text})

    from app.submit import runner
    monkeypatch.setattr(runner, "post_alert", fake_post)
    setup(client, Portal(answers=[401]))
    client.app.state.submitter.alert_url = "https://chat.example/hook"  # type: ignore[attr-defined]
    eid = harbour(client)
    submit(client, eid)
    assert sent == [{"url": "https://chat.example/hook", "text": f"Enrollment {eid} (Harbour Sports Club) was not "
                     "submitted: portal auth failed after 1 attempt(s). It is marked failed."}]
