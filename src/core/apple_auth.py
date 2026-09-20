"""Sign in with Apple, and the session tokens issued from it.

This is the third identity mode (see ``core.auth``). The other two lean on
the network boundary: ``single`` trusts that there is only one user, and
``tailscale`` trusts a header that Serve overwrites. Neither works for an
a native client on the open internet, where the caller is a stranger.

The flow is deliberately two-step:

1. The app signs in with Apple and gets an **identity token** -- a JWT that
   Apple signed. It is verified here against Apple's published keys.
2. That token is exchanged for a **session token** this server signed.

Step 2 exists because Apple's identity token expires in minutes. Treating it
as a session credential means either re-authenticating constantly or keeping
a long-lived Apple refresh token server-side, and neither is worth it when
the app only needs to know which rows are yours.

The owner is ``apple:<sub>``. The ``sub`` claim is stable for a given user
and developer team, which is exactly the property an owner key needs. The
prefix keeps the identity source visible in the database and makes it
impossible for a crafted Tailscale login to collide with an Apple subject.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .optional_deps import require_jwt

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"

OWNER_PREFIX = "apple:"

_SESSION_ISSUER = "wcda"
_DEFAULT_SESSION_DAYS = 90

# Apple rotates its signing keys, so the JWKS is fetched rather than pinned.
# PyJWT's client caches it; one instance is kept so that cache survives
# between requests instead of refetching on every sign-in.
_jwks_client: Any = None


class AppleAuthError(Exception):
    """The token did not check out. The message is safe to show a user."""


@dataclass(frozen=True)
class AppleIdentity:
    subject: str
    email: str | None

    @property
    def owner(self) -> str:
        return f"{OWNER_PREFIX}{self.subject}"


def bundle_id() -> str:
    """The audience Apple tokens must carry: this app's bundle identifier."""
    return os.getenv("WCDA_APPLE_BUNDLE_ID", "").strip()


def session_secret() -> str:
    return os.getenv("WCDA_SESSION_SECRET", "").strip()


def session_lifetime() -> timedelta:
    raw = os.getenv("WCDA_SESSION_DAYS", "").strip()
    try:
        days = int(raw) if raw else _DEFAULT_SESSION_DAYS
    except ValueError:
        days = _DEFAULT_SESSION_DAYS
    return timedelta(days=max(1, days))


def _keys_client() -> Any:
    global _jwks_client
    if _jwks_client is None:
        jwt = require_jwt()
        _jwks_client = jwt.PyJWKClient(APPLE_KEYS_URL)
    return _jwks_client


def hashed_nonce(raw_nonce: str) -> str:
    """What Apple puts in the token when the app sets a nonce.

    The app hashes a random string into the authorization request and sends
    the *raw* string here; Apple echoes the hash. Comparing the two is what
    stops a stolen identity token being replayed against this server.
    """
    return hashlib.sha256(raw_nonce.encode("utf-8")).hexdigest()


def verify_identity_token(token: str, *, nonce: str | None = None) -> AppleIdentity:
    """Check an Apple identity token and return who it says signed in."""
    jwt = require_jwt()
    audience = bundle_id()
    if not audience:
        raise AppleAuthError(
            "This server is not configured for Sign in with Apple "
            "(WCDA_APPLE_BUNDLE_ID is unset)."
        )

    try:
        signing_key = _keys_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=APPLE_ISSUER,
            # Defaults, spelled out because every one of them is load-bearing:
            # an unverified signature, a wrong audience or an expired token
            # each mean this is not a sign-in for this app, right now.
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_aud": True,
                "verify_iss": True,
                "require": ["exp", "iss", "aud", "sub"],
            },
        )
    except Exception as exc:  # PyJWT raises a family of these
        raise AppleAuthError(f"Apple could not be verified: {exc}") from exc

    if nonce is not None:
        expected = hashed_nonce(nonce)
        if claims.get("nonce") != expected:
            raise AppleAuthError("This sign-in does not match the request it answered.")

    subject = str(claims.get("sub") or "").strip()
    if not subject:
        raise AppleAuthError("Apple did not identify the account.")

    email = claims.get("email")
    return AppleIdentity(subject=subject, email=str(email) if email else None)


def issue_session(owner: str, *, now: datetime | None = None) -> tuple[str, datetime]:
    """Mint this server's own session token. Returns (token, expiry)."""
    jwt = require_jwt()
    secret = session_secret()
    if not secret:
        raise AppleAuthError("This server has no session secret configured.")

    issued = now or datetime.now(UTC)
    expires = issued + session_lifetime()
    token = jwt.encode(
        {
            "iss": _SESSION_ISSUER,
            "sub": owner,
            "iat": int(issued.timestamp()),
            "exp": int(expires.timestamp()),
        },
        secret,
        algorithm="HS256",
    )
    return token, expires


def owner_from_session(token: str) -> str:
    """The owner a session token names, or raise."""
    jwt = require_jwt()
    secret = session_secret()
    if not secret:
        raise AppleAuthError("This server has no session secret configured.")

    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer=_SESSION_ISSUER,
            options={"require": ["exp", "iss", "sub"]},
        )
    except Exception as exc:
        raise AppleAuthError("Your session has expired. Sign in again.") from exc

    owner = str(claims.get("sub") or "").strip()
    if not owner:
        raise AppleAuthError("Your session has expired. Sign in again.")
    return owner
