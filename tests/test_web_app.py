"""Smoke tests for app wiring that do not need a database.

The TestClient is used without its context manager so the startup lifespan
(which runs migrations against a real database) does not execute.
"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from core.web_server import app

client = TestClient(app)


class TestWebAppWiring(unittest.TestCase):
    def test_healthz(self) -> None:
        response = client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_index_is_served(self) -> None:
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_security_headers_present(self) -> None:
        response = client.get("/healthz")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])

    def test_service_worker_headers(self) -> None:
        response = client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response.headers["content-type"])
        self.assertEqual(response.headers["Service-Worker-Allowed"], "/")

    def test_analyze_rejects_non_image(self) -> None:
        response = client.post(
            "/api/analyze",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        self.assertEqual(response.status_code, 400)

    def test_recommendation_requires_coffee_data(self) -> None:
        response = client.post("/api/recommendation", json={})
        self.assertEqual(response.status_code, 422)

    def test_recommendation_rejects_non_positive_dose(self) -> None:
        response = client.post(
            "/api/recommendation",
            json={"coffee_data": {"name": "Test"}, "dose_g": 0},
        )
        # Rejected by the schema, before any database work.
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"][0]["loc"], ["body", "dose_g"])

    def test_app_shell_is_revalidated(self) -> None:
        # Without no-cache the browser may serve a stale app.js alongside a
        # fresh style.css, which renders the log cards incorrectly.
        for path in ("/", "/static/app.js", "/static/style.css"):
            response = client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertEqual(response.headers.get("Cache-Control"), "no-cache", path)

    def test_static_assets_are_version_pinned(self) -> None:
        # The ?v= query must be present so a redeploy cannot reuse a cached URL.
        body = client.get("/").text
        self.assertRegex(body, r'href="/static/style\.css\?v=\d+"')
        self.assertRegex(body, r'src="/static/app\.js\?v=\d+"')

    def test_version_references_do_not_drift(self) -> None:
        """sw.js, index.html and /api/version must all agree.

        The app shows a version chip so the user can tell whether a deploy
        reached their phone. That is only trustworthy if the number cannot
        disagree with itself, and it lives in several hand-edited places.
        """
        static = Path(__file__).resolve().parents[1] / "src" / "web" / "static"

        match = re.search(
            r"const CACHE\s*=\s*'wcda-v(\d+)'",
            (static / "sw.js").read_text(encoding="utf-8"),
        )
        self.assertIsNotNone(match, "sw.js CACHE version not found")
        assert match is not None
        cache_version = int(match.group(1))

        # Every page, not just index.html: admin.html pins the same way, and a
        # page left behind at an older ?v= is exactly the torn-cache bug this
        # whole scheme exists to prevent.
        for page in sorted(static.glob("*.html")):
            html = page.read_text(encoding="utf-8")
            pinned = re.findall(r"/static/[\w./-]+\.(?:css|js)\?v=(\d+)", html)
            self.assertTrue(pinned, f"no version-pinned assets in {page.name}")
            self.assertEqual(
                {int(v) for v in pinned},
                {cache_version},
                f"{page.name} ?v= does not match sw.js CACHE",
            )

            # A newly added tag without ?v= would silently escape the pinning.
            unpinned = re.findall(
                r'(?:href|src)="(/static/[\w./-]+\.(?:css|js))"', html
            )
            self.assertEqual(
                unpinned, [], f"unversioned static assets in {page.name}: {unpinned}"
            )

        served = client.get("/api/version").json()
        self.assertEqual(served["asset_version"], cache_version)

    def test_version_endpoint_shape(self) -> None:
        response = client.get("/api/version")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("asset_version", body)
        self.assertIn("engine_version", body)

    def test_recommendation_accepts_a_bean_id_instead_of_coffee_data(self) -> None:
        """A saved coffee is identified by id, not by resending its fields.

        Asserted against the schema rather than the route: reaching the route
        needs a database, and these tests run without one.
        """
        from pydantic import ValidationError

        from core.web_schemas import RecommendationRequest

        self.assertEqual(RecommendationRequest(bean_id=7).bean_id, 7)
        self.assertIsNone(RecommendationRequest(bean_id=7).coffee_data)
        self.assertEqual(
            RecommendationRequest(coffee_data={"name": "Test"}).coffee_data,
            {"name": "Test"},
        )
        with self.assertRaises(ValidationError):
            RecommendationRequest()

    def test_feedback_accepts_a_fractional_shot_time(self) -> None:
        """The wizard's timer reports tenths of a second.

        `time_s: int` rejected every timed shot with a 422, so pressing "Log
        this shot" after using the timer could never save. Asserted at the
        schema, since reaching the route needs a database.
        """
        from core.web_schemas import FeedbackRequest, LogDetailsInput

        body = FeedbackRequest(coffee_data={}, time_s=27.3)
        self.assertEqual(body.time_s, 27.3)
        self.assertEqual(LogDetailsInput(time_s=27.5).time_s, 27.5)

    def test_fractional_shot_time_is_rounded_to_whole_seconds(self) -> None:
        # dial_in_logs.time_s is an Integer column, so the tenths are rounded
        # off at the boundary rather than reaching the database.
        from core.web_helpers import resolve_log_values
        from core.web_schemas import LogDetailsInput

        class _Db:
            """Stands in for the session; the only read is the dose default,
            and returning nothing leaves it on its built-in fallback."""

            def query(self, *_: object) -> _Db:
                return self

            def filter(self, *_: object) -> _Db:
                return self

            def first(self) -> None:
                return None

        values = resolve_log_values(LogDetailsInput(time_s=27.6), _Db(), "owner")
        self.assertEqual(values["time_s"], 28)

    def test_setups_active_route_is_not_shadowed(self) -> None:
        # PUT /api/setups/active must reach select_setup, not be captured by
        # /api/setups/{setup_id} (which would parse "active" as an int).
        response = client.put("/api/setups/active", json={})
        self.assertEqual(response.status_code, 422)
        # Shadowed, the complaint would be about the *path* ("active" is not
        # an int); reaching select_setup, it is the missing body field.
        self.assertEqual(response.json()["detail"][0]["loc"], ["body", "setup_id"])


class TestRequestIdentity(unittest.TestCase):
    """core.auth: which owner a request's data is scoped to.

    The friends instance is multi-user; every user-scoped route now depends on
    `get_owner`. These assert the two modes without a database.
    """

    def setUp(self) -> None:
        self._saved = {
            k: os.environ.get(k) for k in ("WCDA_AUTH_MODE", "WCDA_SINGLE_USER")
        }

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _request(self, headers: dict[str, str] | None = None) -> Any:
        from starlette.datastructures import Headers
        from starlette.requests import Request

        raw = Headers(headers or {}).raw
        return Request({"type": "http", "headers": raw})

    def test_single_mode_maps_every_request_to_one_owner(self) -> None:
        from core.auth import get_owner

        os.environ["WCDA_AUTH_MODE"] = "single"
        os.environ["WCDA_SINGLE_USER"] = "barista"
        # The header a tailscale deployment would trust is ignored here.
        owner = get_owner(self._request({"Tailscale-User-Login": "someone@else"}))
        self.assertEqual(owner, "barista")

    def test_tailscale_mode_takes_the_identity_from_the_header(self) -> None:
        from core.auth import get_owner

        os.environ["WCDA_AUTH_MODE"] = "tailscale"
        owner = get_owner(self._request({"Tailscale-User-Login": "Alice@example.com"}))
        self.assertEqual(owner, "alice@example.com")

    def test_tailscale_mode_rejects_a_request_without_the_header(self) -> None:
        from fastapi import HTTPException

        from core.auth import get_owner

        os.environ["WCDA_AUTH_MODE"] = "tailscale"
        with self.assertRaises(HTTPException) as ctx:
            get_owner(self._request())
        self.assertEqual(ctx.exception.status_code, 401)

    def test_user_scoped_route_is_401_without_an_identity_in_tailscale_mode(
        self,
    ) -> None:
        os.environ["WCDA_AUTH_MODE"] = "tailscale"
        # A well-formed body: the only thing left that can fail is the identity.
        response = client.post(
            "/api/recommendation", json={"coffee_data": {"name": "Test"}}
        )
        self.assertEqual(response.status_code, 401)

    def test_whoami_reports_the_single_user_owner(self) -> None:
        os.environ["WCDA_AUTH_MODE"] = "single"
        os.environ["WCDA_SINGLE_USER"] = "owner"
        response = client.get("/api/whoami")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"owner": "owner", "auth_mode": "single"})

    def test_whoami_reports_the_tailscale_identity(self) -> None:
        os.environ["WCDA_AUTH_MODE"] = "tailscale"
        response = client.get(
            "/api/whoami", headers={"Tailscale-User-Login": "Friend@example.com"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"owner": "friend@example.com", "auth_mode": "tailscale"}
        )

    def test_whoami_is_401_without_an_identity(self) -> None:
        """The one route a confused friend can be asked to open.

        It touches no database, so a 401 here isolates the problem to Tailscale
        identity rather than anything in the app.
        """
        os.environ["WCDA_AUTH_MODE"] = "tailscale"
        response = client.get("/api/whoami")
        self.assertEqual(response.status_code, 401)
        self.assertIn("ts.net", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
