"""Smoke tests for app wiring that do not need a database.

The TestClient is used without its context manager so the startup lifespan
(which runs migrations against a real database) does not execute.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from core.web_server import app

client = TestClient(app)


class TestWebAppWiring(unittest.TestCase):
    def test_healthz(self) -> None:
        response = client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_index_is_served(self) -> None:
        for path in ("/", "/mobile", "/desktop"):
            response = client.get(path)
            self.assertEqual(response.status_code, 200, path)
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
        self.assertEqual(response.status_code, 400)

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

        html = (static / "index.html").read_text(encoding="utf-8")
        pinned = re.findall(r"/static/[\w./-]+\.(?:css|js)\?v=(\d+)", html)
        self.assertTrue(pinned, "no version-pinned assets in index.html")
        self.assertEqual(
            {int(v) for v in pinned},
            {cache_version},
            "index.html ?v= does not match sw.js CACHE",
        )

        # A newly added tag without ?v= would silently escape the pinning.
        unpinned = re.findall(r'(?:href|src)="(/static/[\w./-]+\.(?:css|js))"', html)
        self.assertEqual(unpinned, [], f"unversioned static assets: {unpinned}")

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

    def test_setups_active_route_is_not_shadowed(self) -> None:
        # PUT /api/setups/active must reach select_setup, not be captured by
        # /api/setups/{setup_id} (which would parse "active" as an int).
        response = client.put("/api/setups/active", json={})
        self.assertEqual(response.status_code, 422)
        self.assertIn("setup_id is required", response.text)


if __name__ == "__main__":
    unittest.main()
