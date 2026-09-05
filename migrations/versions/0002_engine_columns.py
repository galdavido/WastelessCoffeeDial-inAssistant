"""engine columns: hardware capability, brew method, measured shot data

Adds the columns the deterministic brewing engine needs, and relaxes the
NOT NULL constraints on dial_in_logs.yield_g/time_s/rating that forced the
application to fabricate values when the user did not supply them.

Hand-written on purpose: `alembic revision --autogenerate` would emit
`op.drop_table('scraped_equipment')`, because that table exists in the
production database but is not modelled in models.py (the database was
stamped, not migrated). Never autogenerate against this project.

Additive and nullable throughout, so it is safe to run against existing
data during the startup lifespan.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- equipment: hardware capability -------------------------------------
    # Replaces the hardcoded Kingrinder K6 click range that used to live in
    # src/ai/rag.py. spec_source is required by convention (not by the DB):
    # a capability row without a citation is a guess.
    op.add_column(
        "equipment", sa.Column("grind_min_clicks", sa.Numeric(6, 2), nullable=True)
    )
    op.add_column(
        "equipment", sa.Column("grind_max_clicks", sa.Numeric(6, 2), nullable=True)
    )
    op.add_column(
        "equipment", sa.Column("grind_step_clicks", sa.Numeric(5, 3), nullable=True)
    )
    op.add_column(
        "equipment", sa.Column("grind_um_per_click", sa.Numeric(6, 2), nullable=True)
    )
    op.add_column("equipment", sa.Column("finer_direction", sa.String(), nullable=True))
    op.add_column("equipment", sa.Column("burr_type", sa.String(), nullable=True))
    op.add_column(
        "equipment", sa.Column("burr_size_mm", sa.Numeric(5, 1), nullable=True)
    )
    op.add_column(
        "equipment", sa.Column("basket_size_g", sa.Numeric(5, 2), nullable=True)
    )
    op.add_column("equipment", sa.Column("temp_min_c", sa.Numeric(4, 1), nullable=True))
    op.add_column("equipment", sa.Column("temp_max_c", sa.Numeric(4, 1), nullable=True))
    op.add_column(
        "equipment",
        sa.Column(
            "temp_controllable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("equipment", sa.Column("spec_source", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_equipment_finer_direction",
        "equipment",
        "finer_direction IS NULL "
        "OR finer_direction IN ('lower_is_finer', 'higher_is_finer')",
    )

    # --- beans --------------------------------------------------------------
    # vision.py already extracts roast_date and then throws it away.
    op.add_column("beans", sa.Column("roast_date", sa.Date(), nullable=True))
    op.add_column(
        "beans", sa.Column("roast_level_ord", sa.SmallInteger(), nullable=True)
    )
    op.create_check_constraint(
        "ck_beans_roast_level_ord",
        "beans",
        "roast_level_ord IS NULL OR roast_level_ord BETWEEN 1 AND 5",
    )

    # --- brew_setups: brew method as a first-class concept -------------------
    op.add_column("brew_setups", sa.Column("method", sa.String(), nullable=True))
    op.create_check_constraint(
        "ck_brew_setups_method",
        "brew_setups",
        "method IS NULL OR method IN ('espresso', 'pourover', 'moka')",
    )

    # --- recommendations: persist every engine output -----------------------
    # Without this there is nothing to back-test proposed-vs-actual against.
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("setup_id", sa.Integer(), nullable=True),
        sa.Column("bean_id", sa.Integer(), nullable=True),
        sa.Column("engine_version", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=True),
        sa.Column("grind_clicks", sa.Numeric(6, 2), nullable=True),
        sa.Column("dose_g", sa.Numeric(5, 2), nullable=True),
        sa.Column("yield_g", sa.Numeric(6, 1), nullable=True),
        sa.Column("water_g", sa.Numeric(6, 1), nullable=True),
        sa.Column("brew_temp_c", sa.Numeric(4, 1), nullable=True),
        sa.Column("target_time_s", sa.Numeric(5, 1), nullable=True),
        sa.Column("basis", sa.String(), nullable=True),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("inputs_json", sa.JSON(), nullable=True),
        sa.Column("rationale_text", sa.Text(), nullable=True),
        sa.Column("llm_model", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["setup_id"], ["brew_setups.id"]),
        sa.ForeignKeyConstraint(["bean_id"], ["beans.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recommendations_id", "recommendations", ["id"])
    op.create_check_constraint(
        "ck_recommendations_basis",
        "recommendations",
        "basis IS NULL OR basis IN ('prior', 'history', 'calibrated')",
    )

    # --- dial_in_logs: measured shot data -----------------------------------
    op.add_column("dial_in_logs", sa.Column("setup_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_dial_in_logs_setup_id", "dial_in_logs", "brew_setups", ["setup_id"], ["id"]
    )
    op.add_column("dial_in_logs", sa.Column("brew_method", sa.String(), nullable=True))
    op.add_column(
        "dial_in_logs", sa.Column("grind_clicks", sa.Numeric(6, 2), nullable=True)
    )
    op.add_column("dial_in_logs", sa.Column("water_g", sa.Numeric(6, 1), nullable=True))
    op.add_column("dial_in_logs", sa.Column("taste_axis", sa.String(), nullable=True))
    op.add_column("dial_in_logs", sa.Column("astringent", sa.Boolean(), nullable=True))
    op.add_column(
        "dial_in_logs", sa.Column("brew_temp_c", sa.Numeric(4, 1), nullable=True)
    )
    op.add_column(
        "dial_in_logs", sa.Column("preinfusion_s", sa.Numeric(4, 1), nullable=True)
    )
    # Optional forever: no code path may require a refractometer.
    op.add_column("dial_in_logs", sa.Column("tds_pct", sa.Numeric(4, 2), nullable=True))
    op.add_column(
        "dial_in_logs",
        sa.Column(
            "data_quality",
            sa.String(),
            nullable=False,
            server_default=sa.text("'measured'"),
        ),
    )
    op.add_column("dial_in_logs", sa.Column("llm_note", sa.Text(), nullable=True))
    op.add_column(
        "dial_in_logs", sa.Column("recommendation_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_dial_in_logs_recommendation_id",
        "dial_in_logs",
        "recommendations",
        ["recommendation_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_dial_in_logs_taste_axis",
        "dial_in_logs",
        "taste_axis IS NULL OR taste_axis IN "
        "('very_sour', 'sour', 'balanced', 'bitter', 'very_bitter')",
    )
    op.create_check_constraint(
        "ck_dial_in_logs_data_quality",
        "dial_in_logs",
        "data_quality IN ('measured', 'partial', 'synthetic', 'imported')",
    )
    op.create_check_constraint(
        "ck_dial_in_logs_brew_method",
        "dial_in_logs",
        "brew_method IS NULL OR brew_method IN ('espresso', 'pourover', 'moka')",
    )

    # --- the constraints that forced fabrication ----------------------------
    # These NOT NULLs are why resolve_log_values() invented yield_g = dose*2,
    # time_s = 28 and rating = 5. Absent measurements must be recorded as
    # absent, not guessed.
    op.alter_column("dial_in_logs", "yield_g", existing_type=sa.Float(), nullable=True)
    op.alter_column("dial_in_logs", "time_s", existing_type=sa.Integer(), nullable=True)
    op.alter_column("dial_in_logs", "rating", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column(
        "dial_in_logs", "rating", existing_type=sa.Integer(), nullable=False
    )
    op.alter_column(
        "dial_in_logs", "time_s", existing_type=sa.Integer(), nullable=False
    )
    op.alter_column("dial_in_logs", "yield_g", existing_type=sa.Float(), nullable=False)

    op.drop_constraint("ck_dial_in_logs_brew_method", "dial_in_logs", type_="check")
    op.drop_constraint("ck_dial_in_logs_data_quality", "dial_in_logs", type_="check")
    op.drop_constraint("ck_dial_in_logs_taste_axis", "dial_in_logs", type_="check")
    op.drop_constraint(
        "fk_dial_in_logs_recommendation_id", "dial_in_logs", type_="foreignkey"
    )
    op.drop_constraint("fk_dial_in_logs_setup_id", "dial_in_logs", type_="foreignkey")
    for column in (
        "recommendation_id",
        "llm_note",
        "data_quality",
        "tds_pct",
        "preinfusion_s",
        "brew_temp_c",
        "astringent",
        "taste_axis",
        "water_g",
        "grind_clicks",
        "brew_method",
        "setup_id",
    ):
        op.drop_column("dial_in_logs", column)

    op.drop_constraint("ck_recommendations_basis", "recommendations", type_="check")
    op.drop_index("ix_recommendations_id", table_name="recommendations")
    op.drop_table("recommendations")

    op.drop_constraint("ck_brew_setups_method", "brew_setups", type_="check")
    op.drop_column("brew_setups", "method")

    op.drop_constraint("ck_beans_roast_level_ord", "beans", type_="check")
    op.drop_column("beans", "roast_level_ord")
    op.drop_column("beans", "roast_date")

    op.drop_constraint("ck_equipment_finer_direction", "equipment", type_="check")
    for column in (
        "spec_source",
        "temp_controllable",
        "temp_max_c",
        "temp_min_c",
        "basket_size_g",
        "burr_size_mm",
        "burr_type",
        "finer_direction",
        "grind_um_per_click",
        "grind_step_clicks",
        "grind_max_clicks",
        "grind_min_clicks",
    ):
        op.drop_column("equipment", column)
