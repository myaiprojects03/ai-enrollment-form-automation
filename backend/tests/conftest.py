from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from datetime import date

import pytest

from app.security.crypto import new_key
from app.security.staff import hash_password

# Tests never read the developer's .env: fresh keys, no Redis, the test database only.
os.environ["APP_ENV"] = "development"
os.environ["ENCRYPTION_KEYS"] = new_key()
os.environ["FINGERPRINT_KEY"] = new_key()
os.environ["OPERATOR_TOKEN"] = "test-operator-token"
os.environ["REDIS_URL"] = ""
os.environ["LLM_PROVIDER"] = "none"
os.environ["GROQ_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["WEBHOOK_SECRET"] = "test-webhook-secret"
REVIEWER, REVIEWER_PASSWORD = "reviewer@example.com", "correct horse battery"
os.environ["STAFF_ACCOUNTS"] = f"{REVIEWER}:{hash_password(REVIEWER_PASSWORD)}"
os.environ["SESSION_SECRET"] = "test-session-secret"
TEST_DB = os.environ.get("TEST_DATABASE_URL", "")
os.environ["DATABASE_URL"] = TEST_DB or "postgresql://nobody@127.0.0.1:1/none"

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

TODAY = date(2026, 11, 24)
needs_db = pytest.mark.skipif(not TEST_DB, reason="set TEST_DATABASE_URL to run the Postgres tests")


def _reset_db() -> None:
    import asyncpg

    async def run() -> None:
        conn = await asyncpg.connect(TEST_DB)
        try:
            await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        finally:
            await conn.close()
    asyncio.run(run())


@pytest.fixture
def client() -> Iterator:
    """The real app against an empty test database."""
    if not TEST_DB:
        pytest.skip("set TEST_DATABASE_URL to run the Postgres tests")
    _reset_db()
    from fastapi.testclient import TestClient

    from app.main import create_app
    with TestClient(create_app()) as c:
        c.headers["Authorization"] = "Bearer test-operator-token"
        yield c


def academy_adult(**over: object) -> dict:
    data = {"first_name": "Amara", "last_name": "Okafor", "date_of_birth": "1998-05-14",
            "email": "amara.okafor@example.com", "phone": "07911 123456", "program": "data-analytics",
            "start_term": "2027-01", "study_mode": "part_time", "address_line1": "14 Mill Lane",
            "city": "Leeds", "postcode": "ls1 4ap", "consent_terms": True}
    data.update(over)
    return data


def academy_minor(**over: object) -> dict:
    data = academy_adult(first_name="Leo", last_name="Grant", date_of_birth="2010-02-03",
                         email="leo.grant@example.com", phone="+44 7911 234567", guardian_name="Hannah Grant",
                         guardian_relationship="parent", guardian_phone="07400 234567")
    data.update(over)
    return data


def club_adult(**over: object) -> dict:
    data = {"full_name": "Sofia Marin", "email": "sofia.marin@example.com", "phone": "07800 345678",
            "date_of_birth": "1991-09-30", "membership_type": "adult", "start_date": "2026-12-01",
            "interests": ["swimming", "yoga"], "emergency_contact_name": "Dan Marin",
            "emergency_contact_phone": "07900 456789", "accept_terms": True}
    data.update(over)
    return data
