"""Unify recorded lectures into classes; drop the chapter/subtopic library

Cohort -> Class becomes the single tree. A Class is now either a live broadcast
(source_kind='live', stream_live_input_uid set, stream_video_uid filled in
post-broadcast) or a direct video upload (source_kind='uploaded',
stream_video_uid set at create time, no live input).

Destructive moves (per product decision):
  - Standalone classes (cohort_id IS NULL) are DELETED — Class.cohort_id
    becomes NOT NULL.
  - Recordings table is dropped; the Stream video UID is folded into classes.
  - The recorded library tree (chapters / subtopics / recorded_lectures) is
    dropped. Lectures with cohort_id NOT NULL are migrated into classes
    (source_kind='uploaded'); orphans (cohort_id IS NULL) are dropped.

Cloudflare Stream videos themselves are not deleted by this migration — we
only drop our pointers to ones we can't place under a cohort.

Revision ID: 20260604_0010
Revises: 20260604_0009
Create Date: 2026-06-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260604_0010"
down_revision: Union[str, None] = "20260604_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Drop classes without a cohort + their child rows (recordings, email_log).
    #    Email_log.class_id is nullable, so NULL it instead of cascade-deleting
    #    the historical reminder record.
    op.execute(
        sa.text(
            "UPDATE email_log SET class_id = NULL "
            "WHERE class_id IN (SELECT id FROM classes WHERE cohort_id IS NULL)"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM recordings "
            "WHERE class_id IN (SELECT id FROM classes WHERE cohort_id IS NULL)"
        )
    )
    op.execute(sa.text("DELETE FROM classes WHERE cohort_id IS NULL"))

    # 2) Add the new columns. source_kind defaults to 'live' for existing rows
    #    (they all came from the live-broadcast flow).
    op.add_column(
        "classes",
        sa.Column(
            "source_kind",
            sa.String(20),
            nullable=False,
            server_default="live",
        ),
    )
    op.add_column(
        "classes",
        sa.Column("stream_video_uid", sa.String(64), nullable=True),
    )

    # 3) Fold recordings.stream_video_uid into classes.stream_video_uid.
    op.execute(
        sa.text(
            "UPDATE classes c "
            "SET stream_video_uid = r.stream_video_uid "
            "FROM recordings r "
            "WHERE r.class_id = c.id AND r.stream_video_uid IS NOT NULL"
        )
    )

    # 4) Migrate recorded_lectures (with cohort_id set) into classes as uploaded
    #    rows. status: 'published'->'ended', 'draft'->'scheduled'. The recorded
    #    lecture's id is preserved so any external references survive.
    op.execute(
        sa.text(
            """
            INSERT INTO classes (
                id, title, description, subject, topic,
                scheduled_start, duration_min,
                access_type, cohort_id, price_single,
                source_kind, stream_live_input_uid, stream_video_uid,
                thumbnail_url, target_exam, target_year,
                status, created_at
            )
            SELECT
                rl.id, rl.title, rl.description, NULL, NULL,
                rl.created_at,
                COALESCE(NULLIF(rl.duration_sec / 60, 0), 60),
                rl.access_type, rl.cohort_id, NULL,
                'uploaded', NULL, rl.cloudflare_stream_uid,
                rl.thumbnail_url, NULL, NULL,
                CASE WHEN rl.status = 'published' THEN 'ended' ELSE 'scheduled' END,
                rl.created_at
            FROM recorded_lectures rl
            WHERE rl.cohort_id IS NOT NULL
            """
        )
    )

    # 5) Now that every class has a cohort, enforce NOT NULL.
    op.alter_column("classes", "cohort_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)

    # 6) Drop the now-redundant tables.
    op.drop_index("ix_recorded_lectures_subtopic", table_name="recorded_lectures")
    op.drop_table("recorded_lectures")
    op.drop_index("ix_subtopics_chapter", table_name="subtopics")
    op.drop_table("subtopics")
    op.drop_index("ix_chapters_order", table_name="chapters")
    op.drop_table("chapters")
    op.drop_table("recordings")


def downgrade() -> None:
    # Recreate the table shells so the migration is reversible structurally.
    # Data is not restorable — we dropped recordings/recorded_lectures rows
    # and folded their UIDs into classes.stream_video_uid (which we leave in
    # place for any code that still reads it).
    op.create_table(
        "recordings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "class_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("classes.id"),
            nullable=False,
        ),
        sa.Column("stream_video_uid", sa.String(64), nullable=True),
        sa.Column("duration_sec", sa.Integer, nullable=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="processing"),
        sa.Column("available_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
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

    op.alter_column(
        "classes", "cohort_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True
    )
    op.drop_column("classes", "stream_video_uid")
    op.drop_column("classes", "source_kind")
