"""multi-user: an owner on every user-scoped row

The friends instance is multi-user (identity from Tailscale; see core.auth).
Before this, beans, dial_in_logs, brew_setups and recommendations had no owner,
and app_settings held global singletons -- active_setup_id, default_dose_g,
default_grind_offset_clicks -- so two people on one instance would overwrite
each other.

This adds ``owner`` to those four tables and to app_settings, whose uniqueness
moves from ``key`` alone to ``(owner, key)``. Every existing row is assigned to
``'owner'`` -- the identity the single-user dev instance uses and the
``WCDA_SINGLE_USER`` default -- so current data stays with its owner.

Hand-written, like every migration here: autogenerate would drop
scraped_equipment, which exists in production but is not modelled.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables that gain an owner column + index. app_settings is handled separately
# because its unique key also changes.
_OWNED_TABLES = ("beans", "dial_in_logs", "brew_setups", "recommendations")

# Pre-multi-user rows belong to the single-user identity.
_BACKFILL_OWNER = "owner"


def upgrade() -> None:
    for table in _OWNED_TABLES:
        op.add_column(table, sa.Column("owner", sa.String(), nullable=True))
        op.execute(f"UPDATE {table} SET owner = '{_BACKFILL_OWNER}'")
        op.alter_column(table, "owner", existing_type=sa.String(), nullable=False)
        op.create_index(f"ix_{table}_owner", table, ["owner"])

    op.add_column("app_settings", sa.Column("owner", sa.String(), nullable=True))
    op.execute(f"UPDATE app_settings SET owner = '{_BACKFILL_OWNER}'")
    op.alter_column("app_settings", "owner", existing_type=sa.String(), nullable=False)
    op.create_index("ix_app_settings_owner", "app_settings", ["owner"])
    # 0001 enforced key-uniqueness with a unique index, not a constraint.
    op.drop_index("ix_app_settings_key", table_name="app_settings")
    op.create_index("ix_app_settings_key", "app_settings", ["key"])
    op.create_unique_constraint(
        "uq_app_settings_owner_key", "app_settings", ["owner", "key"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_app_settings_owner_key", "app_settings", type_="unique")
    op.drop_index("ix_app_settings_key", table_name="app_settings")
    op.create_index("ix_app_settings_key", "app_settings", ["key"], unique=True)
    op.drop_index("ix_app_settings_owner", table_name="app_settings")
    op.drop_column("app_settings", "owner")

    for table in _OWNED_TABLES:
        op.drop_index(f"ix_{table}_owner", table_name=table)
        op.drop_column(table, "owner")
