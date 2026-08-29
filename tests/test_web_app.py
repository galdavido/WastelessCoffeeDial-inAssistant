"""Smoke tests for app wiring that do not need a database.

The TestClient is used without its context manager so the startup lifespan
(which runs migrations against a real database) does not execute.
"""

from __future__ import annotations

import unittest

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

    def test_setups_active_route_is_not_shadowed(self) -> None:
        # PUT /api/setups/active must reach select_setup, not be captured by
        # /api/setups/{setup_id} (which would parse "active" as an int).
        response = client.put("/api/setups/active", json={})
        self.assertEqual(response.status_code, 422)
        self.assertIn("setup_id is required", response.text)


if __name__ == "__main__":
    unittest.main()
