"""Intake to outcome through the HTTP API, against Postgres: uploads of every kind, reviewer edits, the webhook."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_DB, academy_adult, club_adult, needs_db
from tests.test_mapping import NOTES, FakeLLM, _notes_answer

pytestmark = needs_db
RAW = Path(__file__).resolve().parents[2] / "samples" / "raw"
SOON = (date.today() + timedelta(days=10)).isoformat()


def post(client: TestClient, record: dict[str, Any], form: str = "riverside-enrollment", **extra: Any) -> Any:
    return client.post("/api/enrollments", json={"target_form": form, "record": record, **extra})


def upload(client: TestClient, name: str, data: bytes, form: str = "riverside-enrollment") -> Any:
    return client.post("/api/intake/upload", data={"target_form": form}, files={"file": (name, data)})


async def _raw(sql: str, *args: Any) -> list[Any]:
    import asyncpg
    conn = await asyncpg.connect(TEST_DB)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


def raw(sql: str, *args: Any) -> list[Any]:
    import asyncio
    return asyncio.run(_raw(sql, *args))


def test_intake_maps_and_validates_and_shows_no_values(client: TestClient) -> None:
    body = post(client, academy_adult(phone="07911123456")).json()
    assert (body["outcome"], body["status"], body["mapper"]) == ("PASS", "approved", "rules")
    assert body["min_confidence"] >= 0.85
    phone = next(f for f in body["fields"] if f["field"] == "phone")
    assert phone["state"] == "mapped" and "value" not in phone and phone["source_fields"] == ["phone"]
    shown = client.get(f"/api/enrollments/{body['enrollment_id']}", params={"reveal": "true"}).json()
    assert next(f for f in shown["fields"] if f["field"] == "phone")["value"] == "+447911123456"
    assert shown["mapped_payload"]["postcode"] == "LS1 4AP"


def test_field_values_are_encrypted_at_rest(client: TestClient) -> None:
    post(client, academy_adult(date_of_birth="03/04/1999"))
    rows = raw("SELECT value, assumption FROM field_mappings")
    blob = b"".join(bytes(r["value"] or b"") + bytes(r["assumption"] or b"") for r in rows)
    for secret in (b"amara", b"Okafor", b"7911", b"1999", b"Mill Lane", b"LS1"):
        assert secret.lower() not in blob.lower()


def test_reviewer_fixes_a_blocked_record_and_it_passes(client: TestClient) -> None:
    minor = academy_adult(date_of_birth="2010-02-03", email="leo.grant@example.com", phone="07911 234567")
    first = post(client, minor).json()
    assert first["outcome"] == "BLOCKED"
    eid = first["enrollment_id"]
    fixed = client.patch(f"/api/enrollments/{eid}/fields", json={"changes": {
        "guardian_name": "Hannah Grant", "guardian_relationship": "Mum", "guardian_phone": "07400 234567"}}).json()
    assert (fixed["outcome"], fixed["status"]) == ("PASS", "approved"), fixed["reasons"]
    edited = {f["field"]: f for f in fixed["fields"] if f["state"] == "edited"}
    assert set(edited) == {"guardian_name", "guardian_relationship", "guardian_phone"}
    shown = client.get(f"/api/enrollments/{eid}", params={"reveal": "true"}).json()
    assert shown["mapped_payload"]["guardian_relationship"] == "parent"    # normalised like the mapper does
    assert shown["mapped_payload"]["guardian_phone"] == "+447400234567"
    # Mapping again from the source keeps the reviewer's work.
    again = client.post(f"/api/enrollments/{eid}/process").json()
    assert again["outcome"] == "PASS"
    actions = [a["action"] for a in shown["audit"]]
    assert actions.count("fields.edited") == 1 and "validation.outcome" in actions
    edit_entry = next(a for a in shown["audit"] if a["action"] == "fields.edited")
    assert edit_entry["details"] == {"fields": ["guardian_name", "guardian_phone", "guardian_relationship"]}


def test_edits_are_refused_for_unknown_fields_and_finished_records(client: TestClient) -> None:
    eid = post(client, academy_adult()).json()["enrollment_id"]
    assert client.patch(f"/api/enrollments/{eid}/fields", json={"changes": {"shoe": 9}}).status_code == 422
    raw("UPDATE enrollments SET status = 'submitted' WHERE enrollment_id = $1", eid)
    assert client.patch(f"/api/enrollments/{eid}/fields", json={"changes": {"city": "York"}}).status_code == 409


def test_csv_export_upload(client: TestClient) -> None:
    res = upload(client, "riverside-export.csv", (RAW / "riverside-export.csv").read_bytes())
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "csv" and body["records"] == 6
    assert body["outcomes"] == {"PASS": 3, "BLOCKED": 2, "NEEDS_REVIEW": 1}
    tom = body["results"][3]
    assert tom["outcome"] == "BLOCKED" and any(r["field"] == "consent_terms" for r in tom["reasons"])
    # The same file again: nothing new is created.
    again = upload(client, "riverside-export.csv", (RAW / "riverside-export.csv").read_bytes()).json()
    assert all(r["duplicate"] for r in again["results"])
    assert raw("SELECT count(*) AS n FROM enrollments")[0]["n"] == 6


def test_json_upload_with_nested_records(client: TestClient) -> None:
    data = json.loads((RAW / "harbour-signups.json").read_text())
    for r in data["records"]:
        r["start"] = SOON
    body = upload(client, "signups.json", json.dumps(data).encode(), "harbour-membership").json()
    by_name = {r["row"]: r for r in body["results"]}
    assert by_name[1]["status"] == "needs_review" and by_name[1]["outcome"] == "PASS"   # sign-off
    assert by_name[2]["outcome"] == "BLOCKED"            # the student card column needs the AI mapper
    assert by_name[3]["outcome"] == "NEEDS_REVIEW"       # emergency number is the member's own
    assert by_name[4]["outcome"] == "BLOCKED"            # under 16 and terms refused


def _pdf_form(fields: dict[str, str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 780
    for name, value in fields.items():
        c.drawString(50, y + 4, name)
        c.acroForm.textfield(name=name, value=value, x=200, y=y, width=300, height=18)
        y -= 30
    c.save()
    return buf.getvalue()


def _pdf_text(text: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    t = c.beginText(50, 780)
    for line in text.splitlines():
        t.textLine(line)
    c.drawText(t)
    c.save()
    return buf.getvalue()


def test_fillable_pdf_form_upload(client: TestClient) -> None:
    pdf = _pdf_form({"Full Name": "Sofia Marin", "Email": "sofia.marin@example.com", "Phone": "07800 345678",
                     "Date of Birth": "30/09/1991", "Membership": "Adult", "Start Date": SOON,
                     "Interests": "Swimming, Yoga", "Emergency Contact Name": "Dan Marin",
                     "Emergency Contact Phone": "07900 456789", "Terms": "Yes"})
    body = upload(client, "membership.pdf", pdf, "harbour-membership").json()
    assert body["source"] == "pdf" and body["results"][0]["outcome"] == "PASS", body


def test_letter_pdf_is_read_as_notes_by_the_ai(client: TestClient) -> None:
    client.app.state.pipeline.mapper.llm = FakeLLM(_notes_answer())  # type: ignore[attr-defined]
    body = upload(client, "letter.pdf", _pdf_text(NOTES)).json()
    result = body["results"][0]
    assert body["source"] == "pdf" and result["outcome"] == "NEEDS_REVIEW"
    assert [r["field"] for r in result["reasons"]] == ["consent_terms"]   # only the consent waits for a person
    detail = client.get(f"/api/enrollments/{result['enrollment_id']}").json()
    assert detail["mapper"] == "rules+fake:test" and detail["mapping"]["llm_used"] is True


def test_notes_without_an_ai_are_blocked_with_the_reason(client: TestClient) -> None:
    res = client.post("/api/intake/notes", json={"target_form": "riverside-enrollment", "text": NOTES})
    assert res.status_code == 201
    body = res.json()
    assert body["outcome"] == "BLOCKED"
    assert any(r["code"] == "AI_MAPPER_UNAVAILABLE" for r in body["reasons"])


@pytest.mark.parametrize(("name", "data"), [("x.csv", b""), ("x.json", b"[1, 2]"), ("x.docx", b"PK\x03\x04"),
                                            ("x.csv", b"a,b\n")])
def test_unreadable_uploads_are_refused(client: TestClient, name: str, data: bytes) -> None:
    res = upload(client, name, data)
    assert res.status_code == 422 and res.json()["detail"]


def _signed(body: dict[str, Any], secret: str = "test-webhook-secret") -> tuple[bytes, dict[str, str]]:
    raw_body = json.dumps(body).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return raw_body, {"X-Signature": sig, "content-type": "application/json"}


def test_webhook_needs_a_valid_signature_and_is_idempotent(client: TestClient) -> None:
    anon = client   # the webhook ignores the operator token: only the signature counts
    payload = {"target_form": "harbour-membership", "record": club_adult(start_date=SOON),
               "idempotency_key": "crm-hook-1"}
    body, headers = _signed(payload)
    assert anon.post("/api/webhooks/intake", content=body, headers={"content-type": "application/json"}
                     ).status_code == 401
    _, wrong = _signed(payload, "not-the-secret")
    assert anon.post("/api/webhooks/intake", content=body, headers=wrong).status_code == 401
    first = anon.post("/api/webhooks/intake", content=body, headers=headers)
    assert first.status_code == 201 and first.json()["outcome"] == "PASS"
    again = anon.post("/api/webhooks/intake", content=body, headers=headers)
    assert again.status_code == 200 and again.json()["enrollment_id"] == first.json()["enrollment_id"]
    trail = client.get(f"/api/enrollments/{first.json()['enrollment_id']}").json()["audit"]
    assert trail[0]["actor"] == "webhook"


def test_the_same_applicant_twice_is_flagged(client: TestClient) -> None:
    first = post(client, academy_adult()).json()
    second = post(client, academy_adult(program="Accounting")).json()
    assert second["outcome"] == "NEEDS_REVIEW"
    dup = next(r for r in second["reasons"] if r["code"] == "POSSIBLE_DUPLICATE")
    assert first["enrollment_id"] in dup["message"]
