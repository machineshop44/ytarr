"""Sonarr-style authentication: API key + optional Forms (username/password)."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_config

SESSION_COOKIE = "ytarr_session"
SESSION_DAYS = 14

# Paths under /api that stay open (health / login / hub probes)
_PUBLIC_API_SUFFIXES = (
    "/api/ping",
    "/api/health",
    "/api/login",
    "/api/auth/status",
)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    rounds = 200_000
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    stored = (stored or "").strip()
    if not stored or not password:
        return False
    try:
        algo, rounds_s, salt_hex, hash_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        rounds = int(rounds_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


def _session_secret() -> bytes:
    cfg = get_config()
    raw = (cfg.api_key or "ytarr-dev-secret").encode("utf-8")
    return hashlib.sha256(raw + b"|ytarr-session").digest()


def create_session_token(username: str) -> str:
    exp = int(time.time()) + SESSION_DAYS * 86400
    payload = f"{username}|{exp}".encode("utf-8")
    sig = hmac.new(_session_secret(), payload, hashlib.sha256).digest()
    return urlsafe_b64encode(payload).decode("ascii") + "." + urlsafe_b64encode(sig).decode("ascii")


def parse_session_token(token: str) -> str | None:
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload = urlsafe_b64decode(payload_b64.encode("ascii"))
        sig = urlsafe_b64decode(sig_b64.encode("ascii"))
        expected = hmac.new(_session_secret(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        username, exp_s = payload.decode("utf-8").split("|", 1)
        if int(exp_s) < int(time.time()):
            return None
        cfg = get_config()
        if username != (cfg.username or "").strip():
            return None
        return username
    except (ValueError, TypeError):
        return None


def set_session_cookie(response: Response, username: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=create_session_token(username),
        httponly=True,
        samesite="lax",
        max_age=SESSION_DAYS * 86400,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE, path="/")


def session_username(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE) or ""
    if not token:
        return None
    return parse_session_token(token)


def _extract_api_key(request: Request) -> str:
    header = (
        request.headers.get("X-Api-Key")
        or request.headers.get("X-API-Key")
        or request.headers.get("x-api-key")
        or ""
    ).strip()
    if header:
        return header
    return (request.query_params.get("apikey") or request.query_params.get("apiKey") or "").strip()


def api_key_valid(provided: str, expected: str) -> bool:
    if not provided or not expected:
        return False
    try:
        return secrets.compare_digest(provided, expected)
    except (TypeError, ValueError):
        return False


def forms_enabled(cfg=None) -> bool:
    cfg = cfg or get_config()
    method = (getattr(cfg, "authentication_method", None) or "none").strip().lower()
    return method == "forms" and bool((cfg.username or "").strip()) and bool((cfg.password_hash or "").strip())


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path or ""
        if request.method == "OPTIONS":
            return await call_next(request)
        if not path.startswith("/api"):
            return await call_next(request)
        if any(path == p or path.rstrip("/") == p for p in _PUBLIC_API_SUFFIXES):
            return await call_next(request)

        cfg = get_config()
        provided_key = _extract_api_key(request)
        expected_key = (cfg.api_key or "").strip()

        # Mobile hubs / scripts: API key always accepted when configured
        if expected_key and api_key_valid(provided_key, expected_key):
            return await call_next(request)

        # Browser Forms session
        if forms_enabled(cfg) and session_username(request):
            return await call_next(request)

        # Legacy: API-key-only mode without Forms
        if not forms_enabled(cfg):
            if not getattr(cfg, "api_auth_required", True):
                return await call_next(request)
            if expected_key and api_key_valid(provided_key, expected_key):
                return await call_next(request)
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Unauthorized — pass X-Api-Key (or ?apikey=) from Settings → General",
                },
            )

        return JSONResponse(
            status_code=401,
            content={
                "detail": "Unauthorized — log in or pass X-Api-Key",
            },
        )
