"""backfill engine columns and quarantine fabricated log rows

Two jobs:

1. Backfill the columns added in 0002 from data already present
   (grind_setting text -> grind_clicks numeric, setup_id from the
   grinder/machine pair, brew method from the paired equipment,
   roast_level_ord from the roast_level label).

2. Quarantine fabricated rows. Until this release the application invented
   yield_g = dose_g * 2, time_s = 28 and rating = 5 whenever the user did not
   supply them, and stored the LLM's own recommendation prose in
   tasting_notes. Those rows were then retrieved as "your past successful
   shots" and fed back into the next prompt -- the system was learning from
   its own output.

   Matched rows keep their genuine fields (bean, equipment, dose, grind) and
   their prose (moved to llm_note), but the fabricated measurements are set
   to NULL and data_quality is set to 'synthetic'. Nulling as well as
   flagging is deliberate: a query that forgets the data_quality filter then
   fails loudly on None instead of quietly learning that every shot takes
   28 seconds.

Idempotent: every statement is guarded so a re-run is a no-op.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-05
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors normalize_label() in src/core/web_helpers.py: prod contains
# "Medium-light", "Medium Light" and "Medium-Light" for the same thing.
_ROAST_ORDINALS: dict[str, int] = {
    "light": 1,
    "mediumlight": 2,
    "lightmedium": 2,
    "medium": 3,
    "mediumdark": 4,
    "darkmedium": 4,
    "dark": 5,
}

_LEADING_NUMBER = re.compile(r"\s*(-?\d+(?:[.,]\d+)?)")

_POUROVER_MODELS = re.compile(
    r"v60|kalita|chemex|origami|switch|dripper", re.IGNORECASE
)
_MOKA_MODELS = re.compile(r"moka|kotyog|bialetti|brikka", re.IGNORECASE)


def _roast_ordinal(label: str | None) -> int | None:
    if not label:
        return None
    key = re.sub(r"[^a-z]", "", label.lower())
    return _ROAST_ORDINALS.get(key)


def _leading_number(text: str | None) -> float | None:
    if not text:
        return None
    match = _LEADING_NUMBER.match(text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. grind_setting (text) -> grind_clicks (numeric) ------------------
    rows = bind.execute(
        sa.text(
            "SELECT id, grind_setting FROM dial_in_logs "
            "WHERE grind_clicks IS NULL AND grind_setting IS NOT NULL"
        )
    ).all()
    for row_id, grind_setting in rows:
        clicks = _leading_number(grind_setting)
        if clicks is not None:
            bind.execute(
                sa.text("UPDATE dial_in_logs SET grind_clicks = :c WHERE id = :i"),
                {"c": clicks, "i": row_id},
            )

    # --- 2. setup_id from the (grinder, machine) pair -----------------------
    # Only when exactly one setup matches; ambiguous pairs stay NULL.
    bind.execute(
        sa.text(
            """
            UPDATE dial_in_logs AS l
               SET setup_id = s.id
            FROM brew_setups AS s
            WHERE l.setup_id IS NULL
              AND s.grinder_id = l.grinder_id
              AND s.machine_id = l.machine_id
              AND (
                SELECT count(*) FROM brew_setups AS s2
                WHERE s2.grinder_id = l.grinder_id AND s2.machine_id = l.machine_id
              ) = 1
            """
        )
    )

    # --- 3. brew_setups.method from the paired equipment --------------------
    setups = bind.execute(
        sa.text(
            "SELECT s.id, e.type, e.model FROM brew_setups AS s "
            "JOIN equipment AS e ON e.id = s.machine_id "
            "WHERE s.method IS NULL"
        )
    ).all()
    for setup_id, equip_type, model in setups:
        method: str | None = None
        if equip_type == "espresso_machine":
            method = "espresso"
        elif _MOKA_MODELS.search(model or ""):
            method = "moka"
        elif equip_type == "filter" or _POUROVER_MODELS.search(model or ""):
            method = "pourover"
        if method:
            bind.execute(
                sa.text("UPDATE brew_setups SET method = :m WHERE id = :i"),
                {"m": method, "i": setup_id},
            )
    # Setups left NULL surface a required "Brew method" picker in Settings.

    # --- 4. snapshot the method onto historical logs ------------------------
    bind.execute(
        sa.text(
            "UPDATE dial_in_logs AS l SET brew_method = s.method "
            "FROM brew_setups AS s "
            "WHERE l.brew_method IS NULL AND l.setup_id = s.id "
            "AND s.method IS NOT NULL"
        )
    )

    # --- 5. beans.roast_level_ord ------------------------------------------
    beans = bind.execute(
        sa.text("SELECT id, roast_level FROM beans WHERE roast_level_ord IS NULL")
    ).all()
    for bean_id, roast_level in beans:
        ordinal = _roast_ordinal(roast_level)
        if ordinal is not None:
            bind.execute(
                sa.text("UPDATE beans SET roast_level_ord = :o WHERE id = :i"),
                {"o": ordinal, "i": bean_id},
            )

    # --- 6. quarantine fabricated rows --------------------------------------
    # Fingerprint of the old resolve_log_values()/save_dial_in_log() defaults.
    bind.execute(
        sa.text(
            """
            UPDATE dial_in_logs
               SET data_quality = 'synthetic',
                   llm_note = COALESCE(llm_note, tasting_notes),
                   tasting_notes = NULL,
                   yield_g = NULL,
                   time_s = NULL,
                   rating = NULL
             WHERE data_quality <> 'synthetic'
               AND (
                     (
                       yield_g IS NOT NULL AND dose_g IS NOT NULL
                       AND abs(yield_g - dose_g * 2.0) < 0.05
                       AND time_s = 28
                       AND rating = 5
                     )
                     OR tasting_notes LIKE 'Web app: %'
                     OR tasting_notes LIKE 'Discord feedback: %'
                   )
            """
        )
    )

    # Rows that survived but lack the measurements the engine needs are
    # 'partial': usable as exemplars, never as calibration input.
    bind.execute(
        sa.text(
            """
            UPDATE dial_in_logs
               SET data_quality = 'partial'
             WHERE data_quality = 'measured'
               AND (grind_clicks IS NULL OR time_s IS NULL
                    OR (yield_g IS NULL AND water_g IS NULL))
            """
        )
    )


def downgrade() -> None:
    # The fabricated values are deliberately not restored: they were never
    # real measurements. The prose is moved back so no user-visible content
    # is lost.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE dial_in_logs SET tasting_notes = COALESCE(tasting_notes, llm_note), "
            "llm_note = NULL WHERE data_quality = 'synthetic'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE dial_in_logs SET data_quality = 'measured' "
            "WHERE data_quality IN ('synthetic', 'partial')"
        )
    )
