"""The HTTP API, one router per part of the app.

* meta     -- the app shell, health, version, identity
* recipe   -- scan a bag, get a recipe, log the shot you pulled
* coffees  -- the library of coffees and each one's shot history
* gear     -- equipment, setups and settings
"""

from __future__ import annotations

from fastapi import FastAPI

from . import coffees, gear, meta, recipe


def register_routes(app: FastAPI) -> None:
    for module in (meta, recipe, coffees, gear):
        app.include_router(module.router)
