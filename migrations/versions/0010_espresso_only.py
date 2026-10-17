"""espresso only: drop the brew-method and water-in columns

- brew_setups.method, dial_in_logs.brew_method, recommendations.method: the
  brew method a setup, shot or recommendation was for. The app is espresso
  only, so there is nothing left to record.
- dial_in_logs.water_g, recommendations.water_g: water in, the ratio's
  numerator for pour-over and moka. Espresso's is yield_g.

Refuses to run, before changing anything, if any row would lose information:
a non-espresso method, a water_g, or equipment that is neither a grinder nor
an espresso machine. The owner confirmed there are none on dev or prod; the
guard checks rather than trusts it.

Decided by the owner on 2026-10-15
(docs/superpowers/specs/2026-10-15-espresso-only-design.md). Take a dump
first: the downgrade restores the columns, not what was in them.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# What would be lost, by name: each count must be zero. NULL is espresso.
_GUARDS = {
    "brew_setups.method": "SELECT count(*) FROM brew_setups WHERE method <> 'espresso'",
    "dial_in_logs.brew_method": "SELECT count(*) FROM dial_in_logs "
    "WHERE brew_method <> 'espresso'",
    "recommendations.method": "SELECT count(*) FROM recommendations "
    "WHERE method <> 'espresso'",
    "dial_in_logs.water_g": "SELECT count(*) FROM dial_in_logs "
    "WHERE water_g IS NOT NULL",
    "recommendations.water_g": "SELECT count(*) FROM recommendations "
    "WHERE water_g IS NOT NULL",
    "equipment.type": "SELECT count(*) FROM equipment "
    "WHERE type NOT IN ('grinder', 'espresso_machine')",
}

_METHODS = "('espresso', 'pourover', 'moka')"


def upgrade() -> None:
    bind = op.get_bind()
    nonzero = [
        (name, count)
        for name, query in _GUARDS.items()
        if (count := bind.execute(sa.text(query)).scalar_one())
    ]
    if nonzero:
        raise RuntimeError(
            "0010 refused: " + ", ".join(f"{name}={n}" for name, n in nonzero)
        )

    op.drop_constraint("ck_brew_setups_method", "brew_setups", type_="check")
    op.drop_constraint("ck_dial_in_logs_brew_method", "dial_in_logs", type_="check")
    op.drop_column("brew_setups", "method")
    op.drop_column("dial_in_logs", "brew_method")
    op.drop_column("dial_in_logs", "water_g")
    op.drop_column("recommendations", "method")
    op.drop_column("recommendations", "water_g")


def downgrade() -> None:
    # The columns come back empty, with 0002's checks.
    op.add_column("brew_setups", sa.Column("method", sa.String(), nullable=True))
    op.add_column("dial_in_logs", sa.Column("brew_method", sa.String(), nullable=True))
    op.add_column("dial_in_logs", sa.Column("water_g", sa.Numeric(6, 1), nullable=True))
    op.add_column("recommendations", sa.Column("method", sa.String(), nullable=True))
    op.add_column(
        "recommendations", sa.Column("water_g", sa.Numeric(6, 1), nullable=True)
    )
    op.create_check_constraint(
        "ck_brew_setups_method",
        "brew_setups",
        f"method IS NULL OR method IN {_METHODS}",
    )
    op.create_check_constraint(
        "ck_dial_in_logs_brew_method",
        "dial_in_logs",
        f"brew_method IS NULL OR brew_method IN {_METHODS}",
    )
