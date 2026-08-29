"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "beans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("roaster", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("process", sa.String(), nullable=False),
        sa.Column("roast_level", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_beans_id", "beans", ["id"])
    op.create_index("ix_beans_roaster", "beans", ["roaster"])

    op.create_table(
        "equipment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("brand", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_equipment_id", "equipment", ["id"])

    op.create_table(
        "brew_setups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("grinder_id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["grinder_id"], ["equipment.id"]),
        sa.ForeignKeyConstraint(["machine_id"], ["equipment.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brew_setups_id", "brew_setups", ["id"])
    op.create_index("ix_brew_setups_name", "brew_setups", ["name"])

    op.create_table(
        "dial_in_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bean_id", sa.Integer(), nullable=False),
        sa.Column("grinder_id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("grind_setting", sa.String(), nullable=False),
        sa.Column("dose_g", sa.Float(), nullable=False),
        sa.Column("yield_g", sa.Float(), nullable=False),
        sa.Column("time_s", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("tasting_notes", sa.Text(), nullable=True),
        sa.Column("image_path", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["bean_id"], ["beans.id"]),
        sa.ForeignKeyConstraint(["grinder_id"], ["equipment.id"]),
        sa.ForeignKeyConstraint(["machine_id"], ["equipment.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dial_in_logs_id", "dial_in_logs", ["id"])

    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_app_settings_id", "app_settings", ["id"])
    # Unique via the index only, matching Column(String, unique=True, index=True).
    op.create_index("ix_app_settings_key", "app_settings", ["key"], unique=True)


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_index("ix_dial_in_logs_id", table_name="dial_in_logs")
    op.drop_table("dial_in_logs")
    op.drop_index("ix_brew_setups_name", table_name="brew_setups")
    op.drop_index("ix_brew_setups_id", table_name="brew_setups")
    op.drop_table("brew_setups")
    op.drop_index("ix_equipment_id", table_name="equipment")
    op.drop_table("equipment")
    op.drop_index("ix_beans_roaster", table_name="beans")
    op.drop_index("ix_beans_id", table_name="beans")
    op.drop_table("beans")
