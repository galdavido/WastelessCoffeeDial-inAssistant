"""record the pause between pre-infusion and the pull, plus engine indexes

Pre-infusion duration was already stored (0002) but never reached the engine.
The rest between cutting pre-infusion and starting the pull is a separate
variable -- it is when the bed equalises and CO2 escapes -- so it gets its own
column rather than being folded into pre-infusion time.

Why this matters beyond completeness: a shot with longer pre-infusion reaches
full pressure with the bed already saturated and therefore runs *faster* once
pulling. Unrecorded, that looks exactly like the anti-channeling fingerprint
(a finer grind that did not run slower) and would make the engine refuse to go
finer when nothing is wrong.

Hand-written, like every migration here: autogenerate would drop
scraped_equipment, which exists in production but is not modelled.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rest between cutting pre-infusion and starting the pull.
    op.add_column("dial_in_logs", sa.Column("pause_s", sa.Numeric(4, 1), nullable=True))

    # Indexes for the two queries the engine runs on every recommendation.
    op.create_index(
        "ix_dial_in_logs_setup_created",
        "dial_in_logs",
        ["setup_id", "created_at"],
    )
    op.create_index("ix_dial_in_logs_bean", "dial_in_logs", ["bean_id"])
    op.create_index("ix_dial_in_logs_quality", "dial_in_logs", ["data_quality"])


def downgrade() -> None:
    op.drop_index("ix_dial_in_logs_quality", table_name="dial_in_logs")
    op.drop_index("ix_dial_in_logs_bean", table_name="dial_in_logs")
    op.drop_index("ix_dial_in_logs_setup_created", table_name="dial_in_logs")
    op.drop_column("dial_in_logs", "pause_s")
