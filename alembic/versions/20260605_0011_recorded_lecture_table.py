"""Recreate the recorded_lectures table as a standalone library entity.

The 0010 migration unified recorded lectures into classes. This 0011
introduces a NEW, simpler `recorded_lectures` table for standalone admin
uploads: a recorded lecture is not a broadcast, has no scheduled_start, and
lives in its own /library section.

`DROP TABLE IF EXISTS … CASCADE` runs first to absorb any dev DBs that still
have the pre-0010 `recorded_lectures` / `subtopics` / `chapters` shapes
lying around. Then the new table is created with the new columns.

Revision ID: 20260605_0011
Revises: 20260604_0010
Create Date: 2026-06-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260605_0011"
down_revision: Union[str, None] = "20260604_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Absorb any survivors of the pre-0010 schema on dev DBs that never ran
    # 0010 cleanly. CASCADE drops the FK from subtopics → chapters and the FK
    # from recorded_lectures → subtopics in one go.
    op.execute("DROP TABLE IF EXISTS recorded_lectures CASCADE")
    op.execute("DROP TABLE IF EXISTS subtopics CASCADE")
    op.execute("DROP TABLE IF EXISTS chapters CASCADE")

    op.create_table(
        "recorded_lectures",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("subject", sa.String(50), nullable=True),
        sa.Column("topic", sa.String(200), nullable=True),
        sa.Column("recorded_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_min", sa.Integer, nullable=False, server_default="60"),
        sa.Column("access_type", sa.String(20), nullable=False, server_default="free"),
        sa.Column(
            "cohort_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cohorts.id"),
            nullable=False,
        ),
        sa.Column("price_single", sa.Numeric(10, 2), nullable=True),
        sa.Column("stream_video_uid", sa.String(64), nullable=False),
        sa.Column("thumbnail_url", sa.String(1000), nullable=True),
        sa.Column("target_exam", sa.String(10), nullable=True),
        sa.Column("target_year", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_recorded_lectures_cohort_recorded_on",
        "recorded_lectures",
        ["cohort_id", "recorded_on"],
    )


def downgrade() -> None:
    op.drop_index("ix_recorded_lectures_cohort_recorded_on", table_name="recorded_lectures")
    op.drop_table("recorded_lectures")
