"""Single-user password login with an HMAC-signed session cookie. No sign-up."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request

from .config import settings
from .db import session_scope
from .models import Preference

COOKIE = "olr_scout_session"
MAX_AGE = 60 * 60 * 24 * 30


def _secret() -> bytes:
    if settings.secret_key:
        return settings.secret_key.encode()
    with session_scope() as s:
        row = s.get(Preference, "_secret")
        if row is None:
            row = Preference(key="_secret", value=secrets.token_hex(32))
            s.add(row)
        return str(row.value).encode()


def check_password(given: str) -> bool:
    if not settings.password:
        return False
    return hmac.compare_digest(hashlib.sha256(given.encode()).digest(), hashlib.sha256(settings.password.encode()).digest())


def make_token(now: float | None = None) -> str:
    exp = int((now or time.time()) + MAX_AGE)
    msg = f"wes.{exp}".encode()
    sig = hmac.new(_secret(), msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(msg + b"." + sig).decode()


def valid_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        raw = base64.urlsafe_b64decode(token.encode())
    except Exception:
        return False
    if len(raw) < 34:
        return False
    msg, sig = raw[:-33], raw[-32:]
    if not hmac.compare_digest(hmac.new(_secret(), msg, hashlib.sha256).digest(), sig):
        return False
    try:
        return int(msg.split(b".")[1]) > time.time()
    except (IndexError, ValueError):
        return False


def require_user(request: Request) -> None:
    if not valid_token(request.cookies.get(COOKIE)):
        raise HTTPException(status_code=401, detail="login required")
