"""equipment: record who added each entry, so only they can change it

Equipment is a shared catalogue -- everyone on the friends instance can pick
any grinder or brewer in it for a setup. Until now anyone could also *edit*
any entry, and an entry's capability data (click range, microns per click,
basket size) bounds every number the engine recommends. So one friend fixing
"their" grinder's range silently changed the recommendations of everyone else
whose setup used the same row.

``owner`` is the login that added the entry. Only that person may edit or
delete it. A NULL owner means a shared entry -- the seeded baseline hardware,
or one nobody can be identified as having added -- and is read-only for
everyone.

Backfill: an existing row referenced by exactly one owner's setups or shots is
given to that owner, which is the only defensible guess at who added it. On
the single-user dev instance that is every row in use. A row several people
use, or nobody uses, stays NULL (shared, read-only).

Hand-written, like every migration here.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Kept as a constant so tests/test_api_flows.py can run it against known rows.
BACKFILL_SQL = """
        WITH refs AS (
            SELECT grinder_id AS equipment_id, owner FROM brew_setups
            UNION SELECT machine_id, owner FROM brew_setups
            UNION SELECT grinder_id, owner FROM dial_in_logs
            UNION SELECT machine_id, owner FROM dial_in_logs
        ),
        sole AS (
            SELECT equipment_id, min(owner) AS owner
              FROM refs
             GROUP BY equipment_id
            HAVING count(DISTINCT owner) = 1
        )
        UPDATE equipment
           SET owner = sole.owner
          FROM sole
         WHERE equipment.id = sole.equipment_id
           AND equipment.owner IS NULL
"""


def upgrade() -> None:
    op.add_column("equipment", sa.Column("owner", sa.String(), nullable=True))
    op.create_index("ix_equipment_owner", "equipment", ["owner"])
    op.execute(BACKFILL_SQL)


def downgrade() -> None:
    op.drop_index("ix_equipment_owner", table_name="equipment")
    op.drop_column("equipment", "owner")
