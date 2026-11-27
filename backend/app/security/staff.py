"""Staff sign-in for the review console: scrypt password hashes, and short-lived signed sessions.

A session token is base64url(JSON {sub, exp}) + "." + base64url(HMAC-SHA256). It carries no personal data beyond
the reviewer's own email, and the engine checks it on every request; nothing is stored server-side.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

N, R, P = 2**14, 8, 1


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=32)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, digest = stored.split("$")
        if kind != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=32)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, _unb64(digest))


def parse_accounts(setting: str) -> dict[str, str]:
    out = {}
    for item in setting.split(","):
        email, sep, stored = item.strip().partition(":")
        if sep and email and stored:
            out[email.strip().lower()] = stored.strip()
    return out


# A real hash of a random password: unknown emails take as long to refuse as known ones.
_DUMMY = hash_password(os.urandom(12).hex())


def check_login(accounts: dict[str, str], email: str, password: str) -> bool:
    stored = accounts.get(email.strip().lower())
    ok = verify_password(password, stored or _DUMMY)
    return ok and stored is not None


def issue(secret: str, email: str, hours: int) -> tuple[str, int]:
    exp = int(time.time()) + hours * 3600
    body = _b64(json.dumps({"sub": email.lower(), "exp": exp}, separators=(",", ":")).encode())
    sig = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}", exp


def read(secret: str, token: str) -> str | None:
    """The reviewer's email if the token is genuine and unexpired, else None."""
    body, sep, sig = token.partition(".")
    if not secret or not sep:
        return None
    expected = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        data = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or int(data.get("exp", 0)) < time.time():
        return None
    sub = data.get("sub")
    return sub if isinstance(sub, str) else None
