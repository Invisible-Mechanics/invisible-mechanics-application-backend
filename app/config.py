from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"

    database_url: str

    # HS256 secret for our own session JWTs. Must match APP_JWT_SECRET on the
    # web app so its middleware can verify cookies without a backend round-trip.
    app_jwt_secret: str = ""
    # How long an unconsumed magic link / OTP code stays valid.
    magic_link_ttl_min: int = 15
    # How long a session JWT (cookie) stays valid after verify.
    session_ttl_hours: int = 2

    web_origin: str = "http://localhost:3000"

    resend_api_key: str = ""
    mail_from: str = "Invisible Mechanics <onboarding@resend.dev>"
    cron_shared_secret: str = "dev"

    msg91_auth_key: str = ""
    msg91_sender_id: str = "INVMEC"
    msg91_template_id: str = "6a3bfbc30cdff537840d5983"
    msg91_enrollment_template_id: str = "6a3fe5e3e1a64bb4ca04d0f2"
    msg91_otp_expiry_min: int = 15
    masterclass_topic_title: str = "The Art of Problem Solving"
    masterclass_live_at_text: str = "6 July 2026, 6:00 PM IST"

    # Razorpay (one-time payments). Test keys start with rzp_test_.
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    # Cloudflare API (Stream Live + Stream on-demand). Empty token -> Fake
    # clients are used so dev/tests work without a Cloudflare account.
    cloudflare_api_token: str = ""
    cloudflare_account_id: str = ""
    cloudflare_zone_id: str = ""
    cloudflare_zone_name: str = ""
    cloudflare_api_base_url: str = "https://api.cloudflare.com/client/v4"

    # Cloudflare Stream playback. The customer code is part of the playback
    # hostname (customer-<code>.cloudflarestream.com). Signing key id + PEM
    # come from POST /accounts/{id}/stream/keys.
    cloudflare_stream_customer_code: str = ""
    cloudflare_stream_signing_key_id: str = ""
    cloudflare_stream_signing_key_pem: str = ""
    stream_token_ttl_sec: int = 21600
    # Auto-delete live-input recordings this many days after broadcast end.
    stream_recording_retention_days: int = 30
    # Signing secret returned by `PUT /accounts/{id}/stream/webhook`. Used to
    # verify the `Webhook-Signature` header on inbound stream events. Leave
    # blank to disable webhook ingestion (the cron poller is the fallback).
    cloudflare_stream_webhook_secret: str = ""
    # Grace window after scheduled end before a `disconnected` event is allowed
    # to mark the class `ended`. Short disconnects inside the window are
    # treated as transient (encoder hiccup).
    stream_end_grace_min: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def cloudflare_is_configured(settings: Settings | None = None) -> bool:
    """True if the generic Cloudflare API client can make live calls.

    Stream-playback signing has a separate set of creds (customer code +
    signing key PEM) checked by `stream_signing_is_configured`.
    """
    s = settings or get_settings()
    return bool(s.cloudflare_api_token and s.cloudflare_account_id)


def stream_signing_is_configured(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return bool(
        s.cloudflare_stream_customer_code
        and s.cloudflare_stream_signing_key_id
        and s.cloudflare_stream_signing_key_pem
    )


def stream_webhook_is_configured(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return bool(s.cloudflare_stream_webhook_secret)
