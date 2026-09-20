"""Request identity: which user a request's data is scoped to.

Three modes, selected by ``WCDA_AUTH_MODE``:

* ``single`` -- the default, and what the personal dev instance runs. Every
  request belongs to one implicit owner, ``WCDA_SINGLE_USER`` (default
  ``"owner"``). Behaviour is identical to the pre-multi-user app.
* ``tailscale`` -- the friends instance. It is reachable only through
  ``tailscale serve``, which authenticates the caller against the tailnet and
  sets the ``Tailscale-User-Login`` header, overriding anything the client
  sent. The owner is that header, lower-cased; a request without it did not
  come through Serve and is rejected.
* ``apple`` -- a public instance a native client talks to. The owner
  comes from a session token this server issued after verifying a Sign in
  with Apple identity token (see ``core.apple_auth``), so identity rests on
  a signature rather than on the network boundary.

The first two trust the boundary, which is why they are only safe where that
boundary exists: ``tailscale`` mode trusts a header, so it is only safe while
the process is unreachable except via Serve (bound to loopback).
``warn_if_misconfigured`` says so at startup, and refuses to start at all
when ``apple`` mode is missing the secrets that make it more than decorative.
"""

from __future__ import annotations

import logging
import os

from fastapi import HTTPException, Request

from .apple_auth import AppleAuthError, bundle_id, owner_from_session, session_secret

logger = logging.getLogger("wcda.auth")

DEFAULT_OWNER = "owner"

# Header set by `tailscale serve` from the authenticated tailnet identity.
_IDENTITY_HEADER = "Tailscale-User-Login"


def auth_mode() -> str:
    return os.getenv("WCDA_AUTH_MODE", "single").strip().lower() or "single"


def single_user_owner() -> str:
    """The owner every request maps to in ``single`` mode."""
    return os.getenv("WCDA_SINGLE_USER", DEFAULT_OWNER).strip().lower() or DEFAULT_OWNER


def _tailscale_owner(request: Request) -> str:
    login = (request.headers.get(_IDENTITY_HEADER) or "").strip().lower()
    if not login:
        # Serve fills this header for tailnet users, including external users
        # who accepted a node share -- but never for *tagged* devices, which
        # is the likeliest reason a friend who is plainly "on the tailnet"
        # still lands here. Say so, rather than just "no identity".
        raise HTTPException(
            status_code=401,
            detail=(
                "Tailscale did not identify you. Open this app at its "
                "https://...ts.net address rather than by IP, and check you "
                "are signed in to Tailscale. Devices joined with a tag are "
                "not given an identity and cannot sign in here."
            ),
        )
    return login


def _apple_owner(request: Request) -> str:
    header = (request.headers.get("Authorization") or "").strip()
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="Sign in to use this app.",
        )
    try:
        return owner_from_session(token.strip())
    except AppleAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def get_owner(request: Request) -> str:
    """FastAPI dependency: the owner a request's queries must be scoped to."""
    mode = auth_mode()
    if mode == "tailscale":
        return _tailscale_owner(request)
    if mode == "apple":
        return _apple_owner(request)
    return single_user_owner()


def warn_if_misconfigured() -> None:
    """Log a loud reminder when identity rests on the network boundary.

    In ``apple`` mode this is not a warning but a hard stop: without a
    session secret every session token would be forgeable, and without a
    bundle id an identity token from *any* app would be accepted. Starting
    anyway would be an open instance that looks authenticated.
    """
    mode = auth_mode()
    if mode == "tailscale":
        logger.warning(
            "WCDA_AUTH_MODE=tailscale: the %s header is trusted as the user "
            "identity. This process MUST be reachable only via `tailscale serve` "
            "(bound to loopback) or the header can be spoofed.",
            _IDENTITY_HEADER,
        )
        return

    if mode == "apple":
        missing = [
            name
            for name, value in (
                ("WCDA_SESSION_SECRET", session_secret()),
                ("WCDA_APPLE_BUNDLE_ID", bundle_id()),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "WCDA_AUTH_MODE=apple requires " + " and ".join(missing) + ". "
                "Without them this instance would accept forged sessions."
            )
        logger.info(
            "WCDA_AUTH_MODE=apple: identity comes from Sign in with Apple, "
            "audience %s.",
            bundle_id(),
        )
