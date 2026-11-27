"""Review console sign-in."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import operator
from app.config import get_settings
from app.security import staff

router = APIRouter(prefix="/api/auth")
MAX_FAILURES = 5
WINDOW_S = 15 * 60


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


@router.post("/login")
async def login(body: Login, request: Request) -> dict[str, Any]:
    settings = get_settings()
    accounts = staff.parse_accounts(settings.staff_accounts)
    if not accounts or not settings.session_secret:
        raise HTTPException(503, "console sign-in is not set up (STAFF_ACCOUNTS and SESSION_SECRET)")
    shared = request.app.state.shared
    email = body.email.strip().lower()
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    keys = [f"login-fail:{email}", f"login-fail-ip:{ip}"]
    for key in keys:
        if int(await shared.get(key) or 0) >= MAX_FAILURES:
            raise HTTPException(429, "too many failed sign-ins; wait 15 minutes")
    if not staff.check_login(accounts, email, body.password):
        for key in keys:
            await shared.incr(key, WINDOW_S)
        await request.app.state.enrollments.audit(None, "anonymous", "staff.login_failed", {})
        raise HTTPException(401, "wrong email or password")
    for key in keys:
        await shared.delete(key)
    token, exp = staff.issue(settings.session_secret, email, settings.session_hours)
    await request.app.state.enrollments.audit(None, email, "staff.login", {})
    return {"token": token, "expires_at": exp, "email": email}


@router.get("/me")
def me(actor: str = Depends(operator)) -> dict[str, str]:
    return {"actor": actor}
