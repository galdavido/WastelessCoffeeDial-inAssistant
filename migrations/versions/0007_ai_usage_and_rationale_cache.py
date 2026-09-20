"""meter the Gemini calls, and stop paying twice for the same prose

Two tables, both added for the same reason: the Gemini key is one shared
credential with a daily ceiling, and nothing in the app counted what it
spent. A single enthusiastic user could exhaust it for everyone, and the
first anyone would know is that bag scans started failing.

``ai_usage`` is the counter the quota is enforced against -- one row per
owner, calendar month and call kind. The vision call is consumed *before*
it is made, so a scan that fails still counts; anything else means an
invalid image is a free, unlimited Gemini call.

``rationale_cache`` exists because the clients refresh the recommendation
on every dose change, every setup switch and after every saved shot, and
each refresh was writing the prose again from scratch. The key is a hash of
the prompt, so a hit is exactly what the model would have been asked.

Hand-written, like every migration here: autogenerate would drop
scraped_equipment, which exists in production but is not modelled.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "owner", "period", "kind", name="uq_ai_usage_owner_period_kind"
        ),
    )
    op.create_index("ix_ai_usage_owner", "ai_usage", ["owner"])
    op.create_index("ix_ai_usage_period", "ai_usage", ["period"])

    op.create_table(
        "rationale_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("why", sa.Text(), nullable=False),
        sa.Column("what_to_watch", sa.Text(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "owner", "fingerprint", name="uq_rationale_cache_owner_fingerprint"
        ),
    )
    op.create_index("ix_rationale_cache_owner", "rationale_cache", ["owner"])
    op.create_index(
        "ix_rationale_cache_fingerprint", "rationale_cache", ["fingerprint"]
    )


def downgrade() -> None:
    # Both tables are derived: the counters reset and the cache refills.
    # Nothing here is a record of anything the user created.
    op.drop_index("ix_rationale_cache_fingerprint", table_name="rationale_cache")
    op.drop_index("ix_rationale_cache_owner", table_name="rationale_cache")
    op.drop_table("rationale_cache")
    op.drop_index("ix_ai_usage_period", table_name="ai_usage")
    op.drop_index("ix_ai_usage_owner", table_name="ai_usage")
    op.drop_table("ai_usage")
