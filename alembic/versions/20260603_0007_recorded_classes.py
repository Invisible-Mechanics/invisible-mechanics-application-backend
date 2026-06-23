"""recorded classes: chapters, subtopics, recorded_lectures

Adds the on-demand recorded-lecture library. Three new tables form a
chapter -> subtopic -> lecture tree. Videos live in Cloudflare Stream;
we only store the Stream video UID and lecture metadata. Access reuses
the existing entitlements table (no new scope_type needed) — cohort
entitlements + 'all_access' subscriptions both cover paid lectures.

Revision ID: 20260603_0007
Revises: 20260530_0006
Create Date: 2026-06-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260603_0007"
down_revision: Union[str, None] = "20260530_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chapters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("target_exam", sa.String(10), nullable=True),
        sa.Column("target_year", sa.Integer, nullable=True),
        sa.Column("thumbnail_url", sa.String(1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_chapters_order", "chapters", ["order_index"])

    op.create_table(
        "subtopics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "chapter_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chapters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_subtopics_chapter", "subtopics", ["chapter_id", "order_index"])

    op.create_table(
        "recorded_lectures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "subtopic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subtopics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cloudflare_stream_uid", sa.String(64), nullable=False),
        sa.Column("duration_sec", sa.Integer, nullable=True),
        sa.Column("thumbnail_url", sa.String(1000), nullable=True),
        sa.Column("access_type", sa.String(20), nullable=False, server_default="paid"),
        sa.Column(
            "cohort_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cohorts.id"),
            nullable=True,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_recorded_lectures_subtopic", "recorded_lectures", ["subtopic_id", "order_index"]
    )


def downgrade() -> None:
    op.drop_index("ix_recorded_lectures_subtopic", table_name="recorded_lectures")
    op.drop_table("recorded_lectures")
    op.drop_index("ix_subtopics_chapter", table_name="subtopics")
    op.drop_table("subtopics")
    op.drop_index("ix_chapters_order", table_name="chapters")
    op.drop_table("chapters")
