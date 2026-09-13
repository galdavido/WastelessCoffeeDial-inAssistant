"""backfill beans.roast_level_ord from the roast_level label

The column has existed since 0002 but nothing ever wrote it: the ordinal was
derived only on the transient Bean that ``web_routes._bean_for`` builds for a
scanned bag, never on the row that actually gets persisted. So every stored
bean sat at NULL.

That silently disabled two things. ``brewing.temp_band_for_roast`` fell back to
the medium band for every coffee, and the roast-level term in
``retrieval.similarity`` -- the heaviest bean-only term at 0.25 -- could never
contribute, which in turn stopped a new bag borrowing a delta_bean offset from
the coffees it resembles (docs/science.md#beta-law).

The label is already stored, so this is a pure derivation, not a guess. The
mapping mirrors ``web_helpers._ROAST_ORDINALS``; labels outside it (notably
"Unknown") stay NULL, which is the honest value.

Hand-written, like every migration here: autogenerate would drop
scraped_equipment, which exists in production but is not modelled.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Matched against the label lowercased with non-alphanumerics collapsed to
# single spaces, the same normalisation web_helpers.normalize_label applies.
_ORDINALS: dict[str, int] = {
    "light": 1,
    "medium light": 2,
    "light medium": 2,
    "medium": 3,
    "medium dark": 4,
    "dark medium": 4,
    "dark": 5,
}


def upgrade() -> None:
    for label, ordinal in _ORDINALS.items():
        op.execute(
            f"""
            UPDATE beans
               SET roast_level_ord = {ordinal}
             WHERE roast_level_ord IS NULL
               AND trim(regexp_replace(lower(roast_level), '[^a-z0-9]+', ' ', 'g'))
                   = '{label}'
            """
        )


def downgrade() -> None:
    # The column is derived, so there is nothing to preserve. Clearing it
    # returns the table to the state 0005 left it in.
    op.execute("UPDATE beans SET roast_level_ord = NULL")
