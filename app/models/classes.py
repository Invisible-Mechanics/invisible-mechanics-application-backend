import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Class(Base):
    __tablename__ = "classes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(String(50))
    topic: Mapped[str | None] = mapped_column(String(200))

    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_min: Mapped[int] = mapped_column(Integer, default=60, nullable=False)

    access_type: Mapped[str] = mapped_column(String(20), default="free", nullable=False)
    cohort_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cohorts.id"), nullable=False
    )
    price_single: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    # The Cloudflare Stream Live input UID; deleted when the class is deleted.
    stream_live_input_uid: Mapped[str | None] = mapped_column(String(64))

    # The Cloudflare Stream video UID for the post-broadcast recording, set
    # after the broadcast ends (admin auto-attaches via Cloudflare or pastes
    # from the Stream dashboard). Standalone uploaded videos live in
    # `recorded_lectures`, not here.
    stream_video_uid: Mapped[str | None] = mapped_column(String(64))

    thumbnail_url: Mapped[str | None] = mapped_column(String(1000))
    target_exam: Mapped[str | None] = mapped_column(String(10))  # 'jee' | 'neet'
    target_year: Mapped[int | None] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(20), default="scheduled", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
