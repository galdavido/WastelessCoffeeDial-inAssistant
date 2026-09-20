"""Sign in with Apple: what is accepted, and what must not be.

Identity here rests on a signature rather than on the network boundary, so
these check the signature actually carries weight -- a token for another
app, from another issuer, past its expiry, or answering a different request
must all be refused. A real RSA key stands in for Apple's, so the
verification path runs end to end rather than being mocked out.
"""

from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from core import apple_auth
from core.apple_auth import (
    AppleAuthError,
    hashed_nonce,
    issue_session,
    owner_from_session,
    verify_identity_token,
)
from core.auth import get_owner, warn_if_misconfigured

_BUNDLE = "com.galdavido.dialin"
_SECRET = "test-session-secret"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@contextmanager
def env(**values: str | None):
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, was in previous.items():
            if was is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = was


@contextmanager
def apple_mode(**extra: str | None):
    """A configured apple-mode environment, with overrides applied last so a
    test can unset one of the secrets."""
    values: dict[str, str | None] = {
        "WCDA_AUTH_MODE": "apple",
        "WCDA_APPLE_BUNDLE_ID": _BUNDLE,
        "WCDA_SESSION_SECRET": _SECRET,
    }
    values.update(extra)
    with env(**values):
        yield


class _FakeSigningKey:
    key = _KEY.public_key()


class _FakeKeysClient:
    def get_signing_key_from_jwt(self, token: str) -> _FakeSigningKey:
        return _FakeSigningKey()


def _apple_token(**overrides: object) -> str:
    """A token shaped like Apple's, signed with the stand-in key."""
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": apple_auth.APPLE_ISSUER,
        "aud": _BUNDLE,
        "sub": "001234.abcdef0123456789.0001",
        "exp": int((now + timedelta(minutes=10)).timestamp()),
        "iat": int(now.timestamp()),
        "email": "someone@privaterelay.appleid.com",
    }
    claims.update(overrides)
    return jwt.encode(claims, _KEY, algorithm="RS256")


@contextmanager
def apple_keys():
    with patch.object(apple_auth, "_keys_client", return_value=_FakeKeysClient()):
        yield


class TestIdentityToken(unittest.TestCase):
    def test_a_good_token_identifies_the_account(self) -> None:
        with apple_mode(), apple_keys():
            identity = verify_identity_token(_apple_token())

        self.assertEqual(identity.subject, "001234.abcdef0123456789.0001")
        self.assertEqual(identity.email, "someone@privaterelay.appleid.com")
        # The prefix keeps the identity source visible and makes a collision
        # with a Tailscale login impossible.
        self.assertEqual(identity.owner, "apple:001234.abcdef0123456789.0001")

    def test_a_token_for_another_app_is_refused(self) -> None:
        with apple_mode(), apple_keys(), self.assertRaises(AppleAuthError):
            verify_identity_token(_apple_token(aud="com.someone.else"))

    def test_a_token_from_another_issuer_is_refused(self) -> None:
        with apple_mode(), apple_keys(), self.assertRaises(AppleAuthError):
            verify_identity_token(_apple_token(iss="https://evil.example"))

    def test_an_expired_token_is_refused(self) -> None:
        past = int((datetime.now(UTC) - timedelta(minutes=5)).timestamp())
        with apple_mode(), apple_keys(), self.assertRaises(AppleAuthError):
            verify_identity_token(_apple_token(exp=past))

    def test_a_token_signed_by_someone_else_is_refused(self) -> None:
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = jwt.encode(
            {
                "iss": apple_auth.APPLE_ISSUER,
                "aud": _BUNDLE,
                "sub": "attacker",
                "exp": int((datetime.now(UTC) + timedelta(minutes=10)).timestamp()),
            },
            other,
            algorithm="RS256",
        )
        with apple_mode(), apple_keys(), self.assertRaises(AppleAuthError):
            verify_identity_token(forged)

    def test_the_nonce_binds_the_token_to_the_request(self) -> None:
        raw = "a-random-string"
        token = _apple_token(nonce=hashed_nonce(raw))
        with apple_mode(), apple_keys():
            self.assertEqual(
                verify_identity_token(token, nonce=raw).subject,
                "001234.abcdef0123456789.0001",
            )
            # A token captured from a different sign-in must not be replayed.
            with self.assertRaises(AppleAuthError):
                verify_identity_token(token, nonce="a-different-string")

    def test_an_unconfigured_server_refuses_rather_than_accepting_anything(
        self,
    ) -> None:
        with (
            env(WCDA_APPLE_BUNDLE_ID=None),
            apple_keys(),
            self.assertRaises(AppleAuthError),
        ):
            verify_identity_token(_apple_token())


class TestSessionToken(unittest.TestCase):
    def test_round_trip(self) -> None:
        with apple_mode():
            token, expires = issue_session("apple:001234.abc.0001")
            self.assertEqual(owner_from_session(token), "apple:001234.abc.0001")
            self.assertGreater(expires, datetime.now(UTC))

    def test_a_session_signed_with_another_secret_is_refused(self) -> None:
        with apple_mode():
            token, _ = issue_session("apple:001234.abc.0001")
        with (
            env(
                WCDA_AUTH_MODE="apple",
                WCDA_APPLE_BUNDLE_ID=_BUNDLE,
                WCDA_SESSION_SECRET="a-different-secret",
            ),
            self.assertRaises(AppleAuthError),
        ):
            owner_from_session(token)

    def test_an_expired_session_is_refused(self) -> None:
        with apple_mode():
            past = datetime.now(UTC) - timedelta(days=400)
            token, _ = issue_session("apple:001234.abc.0001", now=past)
            with self.assertRaises(AppleAuthError):
                owner_from_session(token)

    def test_lifetime_is_configurable(self) -> None:
        with apple_mode(WCDA_SESSION_DAYS="1"):
            _, expires = issue_session("apple:001234.abc.0001")
            self.assertLess(expires, datetime.now(UTC) + timedelta(days=2))


class _Request:
    def __init__(self, **headers: str) -> None:
        self.headers = headers


class TestOwnerResolution(unittest.TestCase):
    def test_a_valid_session_resolves_to_its_owner(self) -> None:
        with apple_mode():
            token, _ = issue_session("apple:001234.abc.0001")
            owner = get_owner(_Request(Authorization=f"Bearer {token}"))  # type: ignore[arg-type]
        self.assertEqual(owner, "apple:001234.abc.0001")

    def test_no_header_is_a_401(self) -> None:
        with apple_mode(), self.assertRaises(HTTPException) as caught:
            get_owner(_Request())  # type: ignore[arg-type]
        self.assertEqual(caught.exception.status_code, 401)

    def test_a_non_bearer_header_is_a_401(self) -> None:
        with apple_mode(), self.assertRaises(HTTPException) as caught:
            get_owner(_Request(Authorization="Basic abc123"))  # type: ignore[arg-type]
        self.assertEqual(caught.exception.status_code, 401)

    def test_garbage_is_a_401_not_a_500(self) -> None:
        with apple_mode(), self.assertRaises(HTTPException) as caught:
            get_owner(_Request(Authorization="Bearer not-a-token"))  # type: ignore[arg-type]
        self.assertEqual(caught.exception.status_code, 401)

    def test_the_other_modes_are_untouched(self) -> None:
        with env(WCDA_AUTH_MODE="single", WCDA_SINGLE_USER="owner"):
            self.assertEqual(get_owner(_Request()), "owner")  # type: ignore[arg-type]
        with env(WCDA_AUTH_MODE="tailscale"):
            request = _Request(**{"Tailscale-User-Login": "Friend@Example.com"})
            self.assertEqual(get_owner(request), "friend@example.com")  # type: ignore[arg-type]


class TestStartupGuard(unittest.TestCase):
    def test_apple_mode_without_its_secrets_refuses_to_start(self) -> None:
        """Without a session secret every token would be forgeable, and
        without a bundle id an identity token from any app would be
        accepted. Starting anyway is an open instance that looks
        authenticated."""
        for missing in ("WCDA_SESSION_SECRET", "WCDA_APPLE_BUNDLE_ID"):
            with self.subTest(missing=missing), apple_mode(**{missing: None}):
                with self.assertRaises(RuntimeError) as caught:
                    warn_if_misconfigured()
                self.assertIn(missing, str(caught.exception))

    def test_a_configured_apple_instance_starts(self) -> None:
        with apple_mode():
            warn_if_misconfigured()

    def test_the_other_modes_still_only_warn(self) -> None:
        with env(WCDA_AUTH_MODE="tailscale"):
            warn_if_misconfigured()
        with env(WCDA_AUTH_MODE="single"):
            warn_if_misconfigured()


if __name__ == "__main__":
    unittest.main()
