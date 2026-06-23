"""cohort metadata: thumbnail_url, target_exam, target_year

Revision ID: 20260530_0004
Revises: 20260530_0003
Create Date: 2026-05-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260530_0004"
down_revision: Union[str, None] = "20260530_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cohorts", sa.Column("thumbnail_url", sa.String(1000), nullable=True))
    op.add_column("cohorts", sa.Column("target_exam", sa.String(10), nullable=True))
    op.add_column("cohorts", sa.Column("target_year", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("cohorts", "target_year")
    op.drop_column("cohorts", "target_exam")
    op.drop_column("cohorts", "thumbnail_url")
