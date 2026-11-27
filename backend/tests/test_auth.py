"""Review console sign-in, and the queue the console reads."""
from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from app.security import staff
from tests.conftest import REVIEWER, REVIEWER_PASSWORD, academy_adult, academy_minor, needs_db


def test_passwords_hash_and_check() -> None:
    stored = staff.hash_password("a long passphrase")
    assert stored.startswith("scrypt$") and "a long passphrase" not in stored
    assert staff.verify_password("a long passphrase", stored)
    assert not staff.verify_password("a long passphrasf", stored)
    assert not staff.verify_password("x", "not-a-hash")
    accounts = staff.parse_accounts(f" Alex@Example.com:{stored} , broken-entry")
    assert list(accounts) == ["alex@example.com"]
    assert staff.check_login(accounts, "ALEX@example.com", "a long passphrase")
    assert not staff.check_login(accounts, "nobody@example.com", "a long passphrase")


def test_sessions_expire_and_cannot_be_forged() -> None:
    token, exp = staff.issue("secret", "Alex@Example.com", 8)
    assert staff.read("secret", token) == "alex@example.com" and exp > time.time()
    assert staff.read("other-secret", token) is None
    body, sig = token.split(".")
    forged_body, _ = staff.issue("attacker", "boss@example.com", 8)[0].split(".")
    assert staff.read("secret", f"{forged_body}.{sig}") is None
    expired, _ = staff.issue("secret", "alex@example.com", -1)
    assert staff.read("secret", expired) is None
    assert staff.read("secret", "garbage") is None and staff.read("", token) is None


def _login(client: TestClient, password: str = REVIEWER_PASSWORD, email: str = REVIEWER) -> Any:
    return client.post("/api/auth/login", json={"email": email, "password": password})


@needs_db
def test_a_reviewer_signs_in_and_their_name_is_in_the_audit(client: TestClient) -> None:
    res = _login(client)
    assert res.status_code == 200
    token = res.json()["token"]
    as_reviewer = {"Authorization": f"Bearer {token}"}   # replaces the operator token: only the session
    eid = client.post("/api/enrollments", json={"target_form": "riverside-enrollment",
                                                "record": academy_minor(guardian_relationship=None)}).json()
    assert client.get("/api/auth/me", headers=as_reviewer).json() == {"actor": REVIEWER}
    client.patch(f"/api/enrollments/{eid['enrollment_id']}/fields", headers=as_reviewer,
                 json={"changes": {"guardian_relationship": "parent"}})
    trail = client.get(f"/api/enrollments/{eid['enrollment_id']}").json()["audit"]
    assert [a["actor"] for a in trail if a["action"] == "fields.edited"] == [REVIEWER]
    actions = [(a["actor"], a["action"]) for a in client.get("/api/audit").json()]
    assert (REVIEWER, "staff.login") in actions


@needs_db
def test_wrong_passwords_are_refused_then_slowed(client: TestClient) -> None:
    for _ in range(5):
        assert _login(client, "wrong password").status_code == 401
    assert _login(client).status_code == 429      # even the right password, until the window passes
    assert _login(client, email="someone@example.com").status_code == 429   # same address
    actions = [a["action"] for a in client.get("/api/audit").json()]
    assert actions.count("staff.login_failed") == 5


@needs_db
def test_no_token_or_a_bad_one_is_refused(client: TestClient) -> None:
    anon = TestClient(client.app)
    assert anon.get("/api/enrollments").status_code == 401
    anon.headers["Authorization"] = "Bearer " + staff.issue("not-the-secret", REVIEWER, 8)[0]
    assert anon.get("/api/enrollments").status_code == 401


@needs_db
def test_queue_filters_and_counts(client: TestClient) -> None:
    a = client.post("/api/enrollments", json={"target_form": "riverside-enrollment", "record": academy_adult()}).json()
    b = client.post("/api/enrollments", json={"target_form": "riverside-enrollment", "record": academy_adult(
        email="other@example.com", consent_terms="no")}).json()
    assert client.get("/api/enrollments/counts").json() == {"approved": 1, "blocked": 1}
    blocked = client.get("/api/enrollments", params={"status": "blocked"}).json()
    assert [e["enrollment_id"] for e in blocked] == [b["enrollment_id"]]
    assert [e["enrollment_id"] for e in client.get("/api/enrollments", params={"outcome": "PASS"}).json()] == [
        a["enrollment_id"]]
    found = client.get("/api/enrollments", params={"q": a["enrollment_id"][:7].lower()}).json()
    assert a["enrollment_id"] in [e["enrollment_id"] for e in found]
    text = client.get("/api/enrollments").text
    assert "amara" not in text.lower() and "07911" not in text
