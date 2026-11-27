from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.security import staff

# Declared as a security scheme so the API docs page shows an Authorize button and sends the token.
bearer = HTTPBearer(auto_error=False, description="A reviewer's session token, or the OPERATOR_TOKEN from .env")


def operator(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    """Who is calling: a signed-in reviewer (their email, which goes into the audit trail), or "operator" for
    machine callers holding the operator token (n8n, scripts)."""
    settings = get_settings()
    given = creds.credentials.strip() if creds else ""
    if given and settings.operator_token and hmac.compare_digest(given.encode(), settings.operator_token.encode()):
        return "operator"
    reviewer = staff.read(settings.session_secret, given) if given else None
    if reviewer:
        return reviewer
    raise HTTPException(401, "sign in, or send the operator token")
