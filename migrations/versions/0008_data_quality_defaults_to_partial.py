"""dial_in_logs.data_quality defaults to 'partial', not 'measured'

Only 'measured' rows feed calibration, so 'measured' is the one value a row
must never get by accident. Every current code path classifies each shot
explicitly (web_helpers.classify_data_quality), but the column default --
what a row gets when a future path forgets -- was 'measured', i.e. "trust
this". The safe default is 'partial': an unclassified row is kept, shown,
and ignored by the physics until someone says otherwise.

Existing rows are untouched; only the default changes.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "dial_in_logs",
        "data_quality",
        existing_type=sa.String(),
        existing_nullable=False,
        server_default="partial",
    )


def downgrade() -> None:
    op.alter_column(
        "dial_in_logs",
        "data_quality",
        existing_type=sa.String(),
        existing_nullable=False,
        server_default="measured",
    )
