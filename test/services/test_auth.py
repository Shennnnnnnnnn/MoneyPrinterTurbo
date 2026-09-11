import os
from unittest.mock import patch

from app import auth


def test_remember_login_token_is_signed_and_expires():
    with patch.dict(os.environ, {auth.ADMIN_PASSWORD_ENV_VAR: "test-password"}):
        token = auth.create_remember_login_token(now=1_000)

        assert "test-password" not in token
        assert auth.verify_remember_login_token(token, now=1_001)
        assert not auth.verify_remember_login_token(
            token,
            now=1_000 + auth.REMEMBER_LOGIN_TTL_SECONDS,
        )


def test_remember_login_token_is_invalid_after_password_rotation():
    with patch.dict(os.environ, {auth.ADMIN_PASSWORD_ENV_VAR: "old-password"}):
        token = auth.create_remember_login_token(now=1_000)

    with patch.dict(os.environ, {auth.ADMIN_PASSWORD_ENV_VAR: "new-password"}):
        assert not auth.verify_remember_login_token(token, now=1_001)
