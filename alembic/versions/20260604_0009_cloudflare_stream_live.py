"""Replace Zoom with Cloudflare Stream Live on classes + recordings

Drops ``zoom_meeting_id``, ``zoom_join_url``, ``zoom_password`` from
``classes`` and adds ``stream_live_input_uid``. Renames ``recordings.storage_url``
to ``recordings.stream_video_uid`` (semantics change: was an R2 object key,
is now a Cloudflare Stream video UID) and shrinks its width to 64.

Revision ID: 20260604_0009
Revises: 20260603_0008
Create Date: 2026-06-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260604_0009"
down_revision: Union[str, None] = "20260603_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("classes", "zoom_meeting_id")
    op.drop_column("classes", "zoom_join_url")
    op.drop_column("classes", "zoom_password")
    op.add_column(
        "classes",
        sa.Column("stream_live_input_uid", sa.String(64), nullable=True),
    )

    op.alter_column(
        "recordings",
        "storage_url",
        new_column_name="stream_video_uid",
        existing_type=sa.String(1000),
        type_=sa.String(64),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "recordings",
        "stream_video_uid",
        new_column_name="storage_url",
        existing_type=sa.String(64),
        type_=sa.String(1000),
        existing_nullable=True,
    )
    op.drop_column("classes", "stream_live_input_uid")
    op.add_column(
        "classes",
        sa.Column("zoom_password", sa.String(50), nullable=True),
    )
    op.add_column(
        "classes",
        sa.Column("zoom_join_url", sa.String(500), nullable=True),
    )
    op.add_column(
        "classes",
        sa.Column("zoom_meeting_id", sa.String(50), nullable=True),
    )
