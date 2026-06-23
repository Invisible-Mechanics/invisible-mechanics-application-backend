"""Move source_kind='uploaded' Class rows into recorded_lectures; drop source_kind

The 0011 migration introduced a standalone `recorded_lectures` table.
This 0012 finishes the split:
  1. Copy every `Class` row with `source_kind='uploaded'` into
     `recorded_lectures` (mapping scheduled_start → recorded_on).
  2. Delete those Class rows.
  3. Drop the `source_kind` column from `classes` — every remaining row is
     now a live broadcast.

`stream_video_uid` stays on `classes` for the post-broadcast recording case
(live classes still attach a recording after they end).

Cloudflare Stream videos themselves are not touched.

Revision ID: 20260605_0012
Revises: 20260605_0011
Create Date: 2026-06-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260605_0012"
down_revision: Union[str, None] = "20260605_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Copy uploaded classes into recorded_lectures. Skip rows without a UID
    #    (defensive — the form requires one but historical bad rows are dropped
    #    in step 2 either way).
    op.execute(
        sa.text(
            """
            INSERT INTO recorded_lectures (
                id, title, description, subject, topic,
                recorded_on, duration_min,
                access_type, cohort_id, price_single,
                stream_video_uid,
                thumbnail_url, target_exam, target_year,
                created_at
            )
            SELECT
                id, title, description, subject, topic,
                scheduled_start, duration_min,
                access_type, cohort_id, price_single,
                stream_video_uid,
                thumbnail_url, target_exam, target_year,
                created_at
            FROM classes
            WHERE source_kind = 'uploaded' AND stream_video_uid IS NOT NULL
            """
        )
    )

    # 2) Delete the now-migrated uploaded rows.
    op.execute(sa.text("DELETE FROM classes WHERE source_kind = 'uploaded'"))

    # 3) Drop the column.
    op.drop_column("classes", "source_kind")


def downgrade() -> None:
    op.add_column(
        "classes",
        sa.Column(
            "source_kind",
            sa.String(20),
            nullable=False,
            server_default="live",
        ),
    )
    # Data downgrade is intentionally not provided — recorded_lectures rows
    # created by step 1 stay in their new home.
