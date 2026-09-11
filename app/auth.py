"""Shared authentication helpers for the WebUI and HTTP API."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from app.config import config

ADMIN_PASSWORD_ENV_VAR = "MPT_ADMIN_PASSWORD"
REMEMBER_LOGIN_COOKIE_NAME = "mpt_remember_login"
REMEMBER_LOGIN_TTL_SECONDS = 30 * 24 * 60 * 60


def get_webui_password() -> str:
    """Return the WebUI password configured for this process, if any.

    WebUI access is opt-in through an environment variable so credentials do not
    end up in versioned configuration or become visible in the settings UI.
    """

    return os.getenv(ADMIN_PASSWORD_ENV_VAR, "")


def get_api_key() -> object:
    """Return the effective API credential, preferring the process password."""

    return get_webui_password() or config.app.get("api_key", "")


def verify_webui_password(candidate: object) -> bool:
    """Compare a WebUI login attempt without leaking timing information."""

    expected = get_webui_password()
    if not expected or not isinstance(candidate, str):
        return False

    return secrets.compare_digest(
        candidate.encode("utf-8"), expected.encode("utf-8")
    )


def _urlsafe_base64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_base64_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _remember_login_key() -> bytes:
    """Derive a signing key from the current administrator password."""

    password = get_webui_password()
    return hashlib.sha256(
        b"MoneyPrinterTurbo remember-login v1\0" + password.encode("utf-8")
    ).digest()


def create_remember_login_token(now: float | None = None) -> str:
    """Create a signed, expiring WebUI login token without storing a password."""

    if not get_webui_password():
        return ""

    expires_at = int((time.time() if now is None else now) + REMEMBER_LOGIN_TTL_SECONDS)
    payload = _urlsafe_base64_encode(
        json.dumps({"v": 1, "exp": expires_at}, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    signature = hmac.new(
        _remember_login_key(), payload.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{payload}.{_urlsafe_base64_encode(signature)}"


def verify_remember_login_token(token: object, now: float | None = None) -> bool:
    """Validate a browser-stored remember-login token."""

    if not isinstance(token, str) or not get_webui_password():
        return False

    try:
        payload, signature = token.split(".", 1)
        expected_signature = hmac.new(
            _remember_login_key(), payload.encode("ascii"), hashlib.sha256
        ).digest()
        if not secrets.compare_digest(
            _urlsafe_base64_decode(signature), expected_signature
        ):
            return False
        claims = json.loads(_urlsafe_base64_decode(payload))
        expires_at = claims.get("exp")
        return (
            claims.get("v") == 1
            and isinstance(expires_at, int)
            and expires_at > (time.time() if now is None else now)
        )
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return False
