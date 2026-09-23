"""The app's three journeys, end to end through the HTTP API.

Scan a bag, pull a shot, come back to the coffee; manage the library; manage
the hardware. Every request goes through the real routes, the real engine and
a real Postgres -- only the two Gemini calls are stubbed, because they are the
one part that needs the network and neither decides a number.

Each test runs as a fresh Tailscale user, so they are isolated from one another
and from any rows already in the database.
"""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import patch

from PIL import Image

from _db import DatabaseTestCase
from ai.rationale import render_template

_COFFEE = {
    "roaster": "Test Roasters",
    "name": "Kochere",
    "origin": "Ethiopia",
    "process": "Washed",
    "roast_level": "Light",
    "roast_date": None,
}


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (120, 80, 40)).save(buf, format="PNG")
    return buf.getvalue()


def _template_rationale(recipe: Any, label: str, context: str = "") -> Any:
    return render_template(recipe, label), None


class FlowTestCase(DatabaseTestCase):
    """Stubs Gemini, and gives every user a measured grinder to work with."""

    def setUp(self) -> None:
        super().setUp()
        self._patches = [
            patch("core.engine.write_rationale", _template_rationale),
            patch(
                "core.web_routes.analyze_coffee_bag",
                lambda _path: dict(_COFFEE),
            ),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        super().tearDown()

    def make_setup(self, api: Any = None, method: str = "espresso") -> dict[str, Any]:
        """A K6-like grinder on a fixed-temperature machine, made active."""
        api = api or self.api
        grinder = self.ok(
            api.post(
                "/api/equipment/library",
                json={
                    "type": "grinder",
                    "brand": "Test",
                    "model": "Hand grinder",
                    "grind_min_clicks": 0,
                    "grind_max_clicks": 180,
                    "grind_step_clicks": 1,
                    "grind_um_per_click": 16,
                    "finer_direction": "lower_is_finer",
                },
            )
        )["equipment"]
        machine = self.ok(
            api.post(
                "/api/equipment/library",
                json={
                    "type": "espresso_machine" if method == "espresso" else "filter",
                    "brand": "Test",
                    "model": "Brewer",
                },
            )
        )["equipment"]
        setup = self.ok(
            api.post(
                "/api/setups",
                json={
                    "name": "Bench",
                    "grinder_id": grinder["id"],
                    "machine_id": machine["id"],
                    "method": method,
                },
            )
        )["setup"]
        self.ok(api.put("/api/setups/active", json={"setup_id": setup["id"]}))
        return setup

    def scan(self, api: Any = None) -> dict[str, Any]:
        api = api or self.api
        return self.ok(
            api.post("/api/analyze", files={"file": ("bag.png", _png(), "image/png")})
        )

    def log_shot(self, coffee: dict[str, Any], **fields: Any) -> None:
        body = {
            "coffee_data": coffee,
            "recommendation": "",
            "actual_grind": "20",
            "dose_g": 18.0,
            "yield_g": 36.0,
            "time_s": 27.6,
            "taste_axis": "balanced",
        }
        body.update(fields)
        self.ok(self.api.post("/api/feedback", json=body))

    def only_coffee(self, api: Any = None) -> dict[str, Any]:
        entries = self.ok((api or self.api).get("/api/logs"))["entries"]
        self.assertEqual(len(entries), 1, entries)
        return entries[0]


class TestScanAndPull(FlowTestCase):
    def test_a_scan_returns_a_recipe_and_keeps_the_photo(self) -> None:
        self.make_setup()
        body = self.scan()

        self.assertEqual(body["coffee_data"]["name"], "Kochere")
        self.assertIn("image_name", body["coffee_data"])
        recipe = body["recipe"]
        self.assertEqual(recipe["method"], "espresso")
        # A first shot on a grinder with a known um/click: the physics estimate.
        self.assertEqual(recipe["basis"], "prior")
        self.assertIsNotNone(recipe["grind_clicks"])
        self.assertEqual(body["rationale"]["headline"][:5], "grind")

    def test_a_shot_logged_after_a_scan_lands_in_the_library(self) -> None:
        self.make_setup()
        scan = self.scan()
        self.log_shot(scan["coffee_data"])

        coffee = self.only_coffee()
        self.assertEqual(coffee["bean_name"], "Kochere")
        self.assertEqual(coffee["logs_count"], 1)
        latest = coffee["latest_log"]
        self.assertEqual(latest["time_s"], 28, "tenths are rounded to the second")
        self.assertEqual(
            latest["image_url"], f"/api/log-images/{scan['coffee_data']['image_name']}"
        )
        image = self.client.get(latest["image_url"])
        self.assertEqual(image.status_code, 200)

        shots = self.ok(self.api.get(f"/api/beans/{coffee['bean_id']}/shots"))
        self.assertEqual(len(shots["shots"]), 1)
        shot = shots["shots"][0]
        self.assertEqual(shot["data_quality"], "measured")
        self.assertEqual(shot["band"], "in")
        self.assertEqual(shot["grind_clicks"], 20.0)

    def test_returning_to_a_coffee_works_from_its_own_shots(self) -> None:
        self.make_setup()
        scan = self.scan()
        # Ran fast: the next setting has to be finer (lower on this grinder).
        self.log_shot(scan["coffee_data"], time_s=18.0, taste_axis="sour")
        bean_id = self.only_coffee()["bean_id"]

        body = self.ok(self.api.post("/api/recommendation", json={"bean_id": bean_id}))
        self.assertEqual(body["coffee_data"]["bean_id"], bean_id)
        self.assertEqual(body["recipe"]["basis"], "history")
        self.assertLess(body["recipe"]["grind_clicks"], 20.0)
        self.assertIsNotNone(body["recommendation_id"])

    def test_the_dose_on_screen_is_the_dose_the_recipe_is_for(self) -> None:
        """Regression: a coffee with a shot ignored the dose field entirely."""
        self.make_setup()
        self.log_shot(self.scan()["coffee_data"], dose_g=18.0, yield_g=36.0)
        bean_id = self.only_coffee()["bean_id"]

        # Opening the coffee: its own dose, not the user's 16 g default.
        body = self.ok(self.api.post("/api/recommendation", json={"bean_id": bean_id}))
        self.assertEqual(body["recipe"]["dose_g"], 18.0)
        self.assertEqual(body["coffee_data"]["preferred_dose_g"], 18.0)

        # Asking for 20 g gets a 20 g recipe at the same ratio.
        body = self.ok(
            self.api.post(
                "/api/recommendation", json={"bean_id": bean_id, "dose_g": 20}
            )
        )
        self.assertEqual(body["recipe"]["dose_g"], 20.0)
        self.assertEqual(body["recipe"]["yield_g"], 40.0)
        self.assertEqual(body["coffee_data"]["preferred_dose_g"], 20.0)

    def test_the_second_shot_keeps_the_bag_photo_on_the_card(self) -> None:
        self.make_setup()
        scan = self.scan()
        self.log_shot(scan["coffee_data"])
        bean_id = self.only_coffee()["bean_id"]
        self.log_shot({**scan["coffee_data"], "bean_id": bean_id, "image_name": None})

        coffee = self.only_coffee()
        self.assertEqual(coffee["logs_count"], 2)
        self.assertIsNotNone(coffee["latest_log"]["image_url"])

    def test_an_incomplete_shot_is_kept_out_of_calibration(self) -> None:
        self.make_setup()
        scan = self.scan()
        self.log_shot(scan["coffee_data"], time_s=None)
        bean_id = self.only_coffee()["bean_id"]

        shot = self.ok(self.api.get(f"/api/beans/{bean_id}/shots"))["shots"][0]
        self.assertEqual(shot["data_quality"], "partial")
        body = self.ok(self.api.post("/api/recommendation", json={"bean_id": bean_id}))
        self.assertEqual(body["recipe"]["basis"], "prior")


class TestLibrary(FlowTestCase):
    def test_a_coffee_can_be_added_edited_and_deleted_by_hand(self) -> None:
        self.make_setup()
        created = self.ok(
            self.api.post(
                "/api/logs/manual",
                json={
                    "roaster": "Hand",
                    "name": "Typed In",
                    "origin": "Brazil",
                    "process": "Natural",
                    "roast_level": "Medium",
                    "log": {"grind_setting": "22", "time_s": 29, "yield_g": 36},
                },
            )
        )
        bean_id = created["bean_id"]

        self.ok(
            self.api.put(
                f"/api/logs/{bean_id}",
                json={
                    "roaster": "Hand",
                    "name": "Typed In",
                    "origin": "Brazil",
                    "process": "Natural",
                    "roast_level": "Dark",
                    "log": {"grind_setting": "24", "time_s": 30, "rating": 4},
                },
            )
        )
        coffee = self.only_coffee()
        self.assertEqual(coffee["roast_level"], "Dark")
        self.assertEqual(coffee["latest_log"]["grind_setting"], "24")
        self.assertEqual(coffee["logs_count"], 1, "an edit changes the shot in place")

        self.ok(self.api.delete(f"/api/logs/{bean_id}"))
        self.assertEqual(self.ok(self.api.get("/api/logs"))["entries"], [])

    def test_a_coffee_with_recommendations_can_still_be_deleted(self) -> None:
        """Regression: the recommendations FK once made coffees undeletable."""
        self.make_setup()
        self.log_shot(self.scan()["coffee_data"])
        bean_id = self.only_coffee()["bean_id"]
        self.ok(self.api.post("/api/recommendation", json={"bean_id": bean_id}))

        self.ok(self.api.delete(f"/api/logs/{bean_id}"))
        self.assertEqual(self.ok(self.api.get("/api/logs"))["entries"], [])

    def test_one_user_cannot_see_or_touch_another_users_coffee(self) -> None:
        self.make_setup()
        self.log_shot(self.scan()["coffee_data"])
        bean_id = self.only_coffee()["bean_id"]

        stranger = self.another_user()
        self.assertEqual(self.ok(stranger.get("/api/logs"))["entries"], [])
        self.assertEqual(stranger.get(f"/api/beans/{bean_id}/shots").status_code, 404)
        self.assertEqual(
            stranger.post("/api/recommendation", json={"bean_id": bean_id}).status_code,
            404,
        )
        self.assertEqual(stranger.delete(f"/api/logs/{bean_id}").status_code, 404)
        self.assertEqual(len(self.ok(self.api.get("/api/logs"))["entries"]), 1)


class TestSetupsAndSettings(FlowTestCase):
    def test_a_new_user_gets_a_default_setup(self) -> None:
        body = self.ok(self.api.get("/api/setups"))
        self.assertEqual(len(body["setups"]), 1)
        self.assertEqual(body["active_setup_id"], body["setups"][0]["id"])

    def test_setups_can_be_switched_and_the_last_one_is_kept(self) -> None:
        default = self.ok(self.api.get("/api/setups"))["setups"][0]
        mine = self.make_setup()
        self.assertEqual(
            self.ok(self.api.get("/api/setups"))["active_setup_id"], mine["id"]
        )

        self.ok(self.api.delete(f"/api/setups/{mine['id']}"))
        body = self.ok(self.api.get("/api/setups"))
        self.assertEqual(body["active_setup_id"], default["id"])
        self.assertEqual(
            self.api.delete(f"/api/setups/{default['id']}").status_code, 400
        )

    def test_the_default_dose_is_per_user(self) -> None:
        self.ok(self.api.put("/api/settings/dose", json={"dose_g": 17.5}))
        self.assertEqual(self.ok(self.api.get("/api/settings"))["dose_g"], 17.5)
        self.assertEqual(
            self.ok(self.another_user().get("/api/settings"))["dose_g"], 16.0
        )
