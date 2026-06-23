import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Users ---
class UserOut(_ORM):
    id: uuid.UUID
    email: EmailStr
    name: str | None
    phone: str | None
    role: str


# --- Auth (magic link + 6-digit code) ---
class LoginRequestIn(BaseModel):
    email: EmailStr | None = None
    phone: str | None = Field(default=None, min_length=10, max_length=20)
    next: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_one_identifier(self) -> "LoginRequestIn":
        if bool(self.email) == bool(self.phone):
            raise ValueError("provide exactly one of email or phone")
        return self


class LoginRequestOut(BaseModel):
    ok: Literal[True] = True


class LoginVerifyCodeIn(BaseModel):
    email: EmailStr | None = None
    phone: str | None = Field(default=None, min_length=10, max_length=20)
    code: str = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def require_one_identifier(self) -> "LoginVerifyCodeIn":
        if bool(self.email) == bool(self.phone):
            raise ValueError("provide exactly one of email or phone")
        return self


class LoginVerifyLinkIn(BaseModel):
    token: str = Field(min_length=32, max_length=128)


class LoginVerifyOut(BaseModel):
    access_token: str
    expires_at: datetime
    user: UserOut
    next: str | None = None


# --- Cohorts ---
class CohortOut(_ORM):
    id: uuid.UUID
    title: str
    description: str | None
    price: Decimal | None
    early_bird_price: Decimal | None
    early_bird_deadline: datetime | None
    seat_limit: int | None
    seats_taken: int
    start_date: date | None
    end_date: date | None
    status: str
    thumbnail_url: str | None
    target_exam: Literal["jee", "neet"] | None
    target_year: int | None


class CohortCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    price: Decimal | None = None
    early_bird_price: Decimal | None = None
    early_bird_deadline: datetime | None = None
    seat_limit: int | None = Field(default=None, ge=1)
    start_date: date | None = None
    end_date: date | None = None
    status: Literal["open", "closed", "completed"] = "open"
    thumbnail_url: str | None = None
    target_exam: Literal["jee", "neet"] | None = None
    target_year: int | None = Field(default=None, ge=2026, le=2032)


class CohortUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    price: Decimal | None = None
    early_bird_price: Decimal | None = None
    early_bird_deadline: datetime | None = None
    seat_limit: int | None = Field(default=None, ge=1)
    start_date: date | None = None
    end_date: date | None = None
    status: Literal["open", "closed", "completed"] | None = None
    thumbnail_url: str | None = None
    target_exam: Literal["jee", "neet"] | None = None
    target_year: int | None = Field(default=None, ge=2026, le=2032)


# --- Classes ---
class ClassOut(_ORM):
    id: uuid.UUID
    title: str
    description: str | None
    subject: str | None
    topic: str | None
    scheduled_start: datetime
    duration_min: int
    access_type: Literal["free", "paid"]
    cohort_id: uuid.UUID
    price_single: Decimal | None
    stream_video_uid: str | None
    status: Literal["scheduled", "live", "ended"]
    thumbnail_url: str | None
    target_exam: Literal["jee", "neet"] | None
    target_year: int | None


class ClassCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    subject: str | None = None
    topic: str | None = None
    scheduled_start: datetime
    duration_min: int = Field(ge=15, le=240, default=60)
    access_type: Literal["free", "paid"] = "free"
    cohort_id: uuid.UUID
    price_single: Decimal | None = None
    thumbnail_url: str | None = None
    target_exam: Literal["jee", "neet"] | None = None
    target_year: int | None = Field(default=None, ge=2026, le=2032)


class ClassStatusUpdate(BaseModel):
    status: Literal["scheduled", "live", "ended"]


class ClassUpdate(BaseModel):
    """PATCH body. Only fields the client actually sends are applied
    (via model_dump(exclude_unset=True)). Sending `"thumbnail_url": null`
    clears the field; omitting it leaves the existing value alone."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    subject: str | None = None
    topic: str | None = None
    scheduled_start: datetime | None = None
    duration_min: int | None = Field(default=None, ge=15, le=240)
    access_type: Literal["free", "paid"] | None = None
    cohort_id: uuid.UUID | None = None
    price_single: Decimal | None = None
    stream_video_uid: str | None = Field(default=None, max_length=64)
    thumbnail_url: str | None = None
    target_exam: Literal["jee", "neet"] | None = None
    target_year: int | None = Field(default=None, ge=2026, le=2032)
    status: Literal["scheduled", "live", "ended"] | None = None


# --- Entitlements ---
class EntitlementOut(_ORM):
    id: uuid.UUID
    scope_type: Literal["class", "cohort", "all_access"]
    scope_id: uuid.UUID | None
    source: str
    valid_until: datetime | None
    status: Literal["active", "revoked"]


# --- Join response ---
class JoinResponse(BaseModel):
    """Signed HLS playback for the live broadcast (Cloudflare Stream Live)."""

    hls_url: str
    dash_url: str
    iframe_url: str
    expires_at: datetime


# --- Admin: instructor RTMPS keys for the live input ---
class StreamKeysOut(BaseModel):
    """RTMPS push credentials the instructor configures in OBS / their encoder.

    Treat the stream_key as a secret — never expose to students.
    """

    rtmps_url: str
    rtmps_stream_key: str
    live_input_uid: str


# --- Payments / enrollment ---
class CreateOrderResponse(BaseModel):
    """Everything the browser needs to open Razorpay Checkout."""

    order_id: str
    amount: int  # paise
    currency: str
    key_id: str
    title: str  # cohort or class title, shown in the Razorpay checkout
    prefill_name: str | None = None
    prefill_email: str | None = None
    prefill_contact: str | None = None


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class VerifyPaymentResponse(BaseModel):
    status: Literal["enrolled"]


# --- Recording attach (admin) + student playback ---
class RecordingAttach(BaseModel):
    """Admin attaches the post-broadcast Cloudflare Stream video UID to a class."""

    stream_video_uid: str = Field(min_length=1, max_length=64)


class RecordingPlaybackResponse(BaseModel):
    hls_url: str
    dash_url: str
    iframe_url: str
    expires_at: datetime


# --- Recorded lectures (standalone, Library) ---
class RecordedLectureOut(_ORM):
    id: uuid.UUID
    title: str
    description: str | None
    subject: str | None
    topic: str | None
    recorded_on: datetime
    duration_min: int
    access_type: Literal["free", "paid"]
    cohort_id: uuid.UUID
    price_single: Decimal | None
    stream_video_uid: str
    thumbnail_url: str | None
    target_exam: Literal["jee", "neet"] | None
    target_year: int | None


class RecordedLectureCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    subject: str | None = None
    topic: str | None = None
    recorded_on: datetime
    duration_min: int = Field(ge=1, le=600, default=60)
    access_type: Literal["free", "paid"] = "free"
    cohort_id: uuid.UUID
    price_single: Decimal | None = None
    stream_video_uid: str = Field(min_length=1, max_length=64)
    thumbnail_url: str | None = None
    target_exam: Literal["jee", "neet"] | None = None
    target_year: int | None = Field(default=None, ge=2026, le=2032)


class RecordedLectureUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    subject: str | None = None
    topic: str | None = None
    recorded_on: datetime | None = None
    duration_min: int | None = Field(default=None, ge=1, le=600)
    access_type: Literal["free", "paid"] | None = None
    cohort_id: uuid.UUID | None = None
    price_single: Decimal | None = None
    stream_video_uid: str | None = Field(default=None, min_length=1, max_length=64)
    thumbnail_url: str | None = None
    target_exam: Literal["jee", "neet"] | None = None
    target_year: int | None = Field(default=None, ge=2026, le=2032)
