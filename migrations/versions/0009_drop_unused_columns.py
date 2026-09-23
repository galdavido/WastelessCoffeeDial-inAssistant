"""drop what nothing reads: two columns, a retired setting, scraped_equipment

- dial_in_logs.llm_note: the prose each shot used to be logged with. No
  longer written; the explanation lives on recommendations.rationale_text.
- equipment.burr_size_mm: never written or read.
- app_settings rows keyed default_grind_offset_clicks: the removed
  grind-offset setting, which the engine never read.
- scraped_equipment, and the `vector` extension only it used: an unmodelled
  leftover of the pre-Alembic schema, empty on both live databases. Dropping
  it is what makes the extension removable, and with no vector column left
  the pgvector image is no longer load-bearing.

dial_in_logs.tds_pct stays: it is reserved for a refractometer reading
(docs/science.md).

Decided by the owner on 2026-09-23 (docs/open-decisions.md #4). Take a dump
first: the downgrade restores the columns, not what was in them.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("dial_in_logs", "llm_note")
    op.drop_column("equipment", "burr_size_mm")
    op.execute("DELETE FROM app_settings WHERE key = 'default_grind_offset_clicks'")
    # IF EXISTS: a database built by these migrations alone (CI, tests) never
    # had either.
    op.execute("DROP TABLE IF EXISTS scraped_equipment")
    op.execute("DROP EXTENSION IF EXISTS vector")


def downgrade() -> None:
    # The columns come back empty. scraped_equipment and the extension are not
    # recreated: nothing modelled them, and plain postgres has no `vector`.
    op.add_column(
        "equipment", sa.Column("burr_size_mm", sa.Numeric(5, 1), nullable=True)
    )
    op.add_column("dial_in_logs", sa.Column("llm_note", sa.Text(), nullable=True))
