import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Cohort(Base):
    __tablename__ = "cohorts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    early_bird_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    early_bird_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    seat_limit: Mapped[int | None] = mapped_column(Integer)
    seats_taken: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)

    thumbnail_url: Mapped[str | None] = mapped_column(String(1000))
    target_exam: Mapped[str | None] = mapped_column(String(10))  # 'jee' | 'neet'
    target_year: Mapped[int | None] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
