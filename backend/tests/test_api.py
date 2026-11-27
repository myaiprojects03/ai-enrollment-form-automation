"""The HTTP surface: auth, intake status codes, idempotency header, reveal is audited."""
from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import academy_adult, club_adult, needs_db

pytestmark = needs_db


def post(client: TestClient, record: dict[str, Any], **extra: Any) -> Any:
    headers = extra.pop("headers", None)
    body = {"target_form": "riverside-enrollment", "source": "webhook", "record": record, **extra}
    return client.post("/api/enrollments", json=body, headers=headers)


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "database": True, "shared_state": True}


def test_operator_token_required(client: TestClient) -> None:
    anon = TestClient(client.app)
    assert anon.get("/api/forms").status_code == 401
    assert anon.get("/api/forms", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert anon.post("/api/enrollments", json={}).status_code == 401


def test_forms_are_listed(client: TestClient) -> None:
    ids = {f["id"] for f in client.get("/api/forms").json()}
    assert ids == {"riverside-enrollment", "harbour-membership"}


def test_intake_created_then_replayed(client: TestClient) -> None:
    first = post(client, academy_adult(), idempotency_key="crm-9")
    assert first.status_code == 201
    body = first.json()
    assert body["enrollment_id"].startswith("ENR-") and not body["duplicate"]
    assert (body["outcome"], body["status"]) == ("PASS", "approved")
    again = post(client, academy_adult(), idempotency_key="crm-9")
    assert again.status_code == 200 and again.json()["duplicate"]
    assert again.json()["enrollment_id"] == body["enrollment_id"]


def test_idempotency_header_is_honoured(client: TestClient) -> None:
    a = post(client, club_adult(), target_form="harbour-membership", headers={"Idempotency-Key": "hdr-1"})
    b = post(client, club_adult(), target_form="harbour-membership", headers={"Idempotency-Key": "hdr-1"})
    assert (a.status_code, b.status_code) == (201, 200)


def test_bad_requests(client: TestClient) -> None:
    assert post(client, academy_adult(), target_form="nope").status_code == 422
    assert post(client, {}).status_code == 422
    assert post(client, academy_adult(), source="fax").status_code == 422


def test_responses_never_carry_personal_data_unless_revealed(client: TestClient) -> None:
    eid = post(client, academy_adult(), idempotency_key="pii-1").json()["enrollment_id"]
    for text in (client.get("/api/enrollments").text, client.get(f"/api/enrollments/{eid}").text):
        assert "amara" not in text.lower() and "07911" not in text
    shown = client.get(f"/api/enrollments/{eid}", params={"reveal": "true"}).json()
    assert shown["source_record"]["email"] == "amara.okafor@example.com"
    trail = client.get(f"/api/enrollments/{eid}").json()["audit"]
    assert [a["action"] for a in trail] == ["enrollment.received", "mapping.completed", "validation.outcome",
                                            "personal_data.viewed"]


def test_unknown_enrollment(client: TestClient) -> None:
    assert client.get("/api/enrollments/ENR-NOPE").status_code == 404


def test_possible_duplicates_surface(client: TestClient) -> None:
    first = post(client, academy_adult()).json()
    second = post(client, academy_adult(program="cyber-security")).json()
    assert second["possible_duplicates"] == [first["enrollment_id"]]
