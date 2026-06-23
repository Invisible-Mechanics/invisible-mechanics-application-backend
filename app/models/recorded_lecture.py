import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RecordedLecture(Base):
    """A standalone recorded video uploaded by the admin.

    Distinct from a live `Class` recording: a `Class` represents a broadcast
    event whose post-broadcast recording lives on `Class.stream_video_uid`.
    A `RecordedLecture` has no broadcast — admin pastes a Cloudflare Stream
    video UID at create time and it's immediately playable in the Library.
    """

    __tablename__ = "recorded_lectures"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(String(50))
    topic: Mapped[str | None] = mapped_column(String(200))

    recorded_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_min: Mapped[int] = mapped_column(Integer, default=60, nullable=False)

    access_type: Mapped[str] = mapped_column(String(20), default="free", nullable=False)
    cohort_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cohorts.id"), nullable=False
    )
    price_single: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    stream_video_uid: Mapped[str] = mapped_column(String(64), nullable=False)

    thumbnail_url: Mapped[str | None] = mapped_column(String(1000))
    target_exam: Mapped[str | None] = mapped_column(String(10))
    target_year: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
