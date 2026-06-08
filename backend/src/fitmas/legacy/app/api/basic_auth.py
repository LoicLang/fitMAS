"""HTTP Basic auth gate for the whole webapp/API.

Enabled only when ``FITMAS_APP_PASSWORD`` is set (no-op otherwise, so local dev and
tests are unaffected). ``/health`` stays open so the platform health check passes.
The Telegram coach is a separate process and is not affected by this.
"""
from __future__ import annotations

import base64
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_EXEMPT_PREFIXES = ("/health",)
_DEFAULT_USER = "loic"


def _authorized(header: str, password: str) -> bool:
    if not header.startswith("Basic "):
        return False
    try:
        user, _, pw = base64.b64decode(header[6:]).decode("utf-8").partition(":")
    except Exception:
        return False
    expected_user = os.getenv("FITMAS_APP_USER", _DEFAULT_USER)
    # constant-time compares to avoid leaking length/timing
    return secrets.compare_digest(user, expected_user) and secrets.compare_digest(pw, password)


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        password = os.getenv("FITMAS_APP_PASSWORD")
        if not password:
            return await call_next(request)  # auth disabled
        if any(request.url.path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return await call_next(request)
        if _authorized(request.headers.get("Authorization", ""), password):
            return await call_next(request)
        return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="FitMAS"'})
