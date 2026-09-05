"""Backwards-compatible shim over the deterministic engine.

This module used to be the recommendation: a SQL lookup on exact string
matches, a large prompt, a free-text answer from Gemini, and a regex that
pulled the grind number back out of that prose. The numbers therefore came
from a language model, and because logs stored the same prose, the next
prompt was partly the model's own previous output.

That is all gone. core.engine.recommend() decides every number by arithmetic
over the user's measured shots, and ai.rationale writes the explanation with
no ability to introduce a figure of its own.

What remains here is a thin adapter so the CLI (core.main) and any older
caller still get a printable string. New code should call core.engine
directly and read the structured `recipe` instead of parsing text.
"""

from __future__ import annotations

from typing import Any

from core.engine import recommend, render_legacy_text
from core.web_helpers import find_existing_bean, get_active_setup, get_default_dose_g
from database.database import SessionLocal
from database.models import Bean


def get_best_grind_setting(coffee_json: dict[str, Any]) -> str:
    """Return a printable recommendation for a scanned coffee.

    Deprecated: prefer core.engine.recommend(), which returns the numbers as
    structured fields rather than embedded in prose.
    """
    db = SessionLocal()
    try:
        name = str(coffee_json.get("name") or "Unknown")
        roaster = str(coffee_json.get("roaster") or "Unknown")
        origin = str(coffee_json.get("origin") or "Unknown")
        process = str(coffee_json.get("process") or "Unknown")

        bean = find_existing_bean(
            db, name=name, roaster=roaster, origin=origin, process=process
        )
        if bean is None:
            bean = Bean(
                roaster=roaster,
                name=name,
                origin=origin,
                process=process,
                roast_level=str(coffee_json.get("roast_level") or "Unknown"),
            )

        setup = get_active_setup(db)
        dose = coffee_json.get("preferred_dose_g") or get_default_dose_g(db)
        result = recommend(db, setup, bean, float(dose))
        return render_legacy_text(result)
    except Exception as exc:  # pragma: no cover - defensive, as before
        return f"Error occurred while building the recommendation: {exc}"
    finally:
        db.close()
