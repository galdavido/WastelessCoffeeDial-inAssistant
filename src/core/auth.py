"""Request identity: which user a request's data is scoped to.

Two modes, selected by ``WCDA_AUTH_MODE``:

* ``single`` -- the default, and what the personal dev instance runs. Every
  request belongs to one implicit owner, ``WCDA_SINGLE_USER`` (default
  ``"owner"``). Behaviour is identical to the pre-multi-user app.
* ``tailscale`` -- the friends instance. It is reachable only through
  ``tailscale serve``, which authenticates the caller against the tailnet and
  sets the ``Tailscale-User-Login`` header, overriding anything the client
  sent. The owner is that header, lower-cased; a request without it did not
  come through Serve and is rejected.

The ``tailscale`` mode trusts a header, so it is only safe while the process
is unreachable except via Serve (bind to loopback). ``warn_if_misconfigured``
logs that reminder at startup.
"""

from __future__ import annotations

import logging
import os

from fastapi import HTTPException, Request

logger = logging.getLogger("wcda.auth")

DEFAULT_OWNER = "owner"

# Header set by `tailscale serve` from the authenticated tailnet identity.
_IDENTITY_HEADER = "Tailscale-User-Login"


def auth_mode() -> str:
    return os.getenv("WCDA_AUTH_MODE", "single").strip().lower() or "single"


def single_user_owner() -> str:
    """The owner every request maps to in ``single`` mode."""
    return os.getenv("WCDA_SINGLE_USER", DEFAULT_OWNER).strip().lower() or DEFAULT_OWNER


def get_owner(request: Request) -> str:
    """FastAPI dependency: the owner a request's queries must be scoped to."""
    if auth_mode() == "tailscale":
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
    return single_user_owner()


def warn_if_misconfigured() -> None:
    """Log a loud reminder when identity rests on the network boundary."""
    if auth_mode() == "tailscale":
        logger.warning(
            "WCDA_AUTH_MODE=tailscale: the %s header is trusted as the user "
            "identity. This process MUST be reachable only via `tailscale serve` "
            "(bound to loopback) or the header can be spoofed.",
            _IDENTITY_HEADER,
        )
