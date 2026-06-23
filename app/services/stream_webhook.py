"""Cloudflare Stream webhook ingestion + the live-input state machine.

Two responsibilities, intentionally kept in one module so the wire-protocol
side (parse/verify) and the domain side (state transitions) stay close:

  - `verify_stream_webhook_signature` parses the `Webhook-Signature` header
    (`time=<unix>,sig1=<hex>`) and HMAC-SHA256 verifies the body. The 5-minute
    replay window matches Cloudflare's documented behavior.
  - `apply_live_input_event` owns the scheduled → live → ended transitions
    plus auto-attach of the broadcast recording. Both the webhook router and
    the cron poller dispatch into it so the state machine lives in one place.

Why event_kind is an internal vocabulary rather than the raw Cloudflare
`eventType` string: the cron path derives "connected"/"disconnected" from
`get_status().connected`, not from a webhook payload. Normalizing on the way
in keeps the state machine independent of how the signal arrived.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Class
from app.services.stream_live import StreamLiveClient

logger = logging.getLogger(__name__)


EventKind = Literal["connected", "disconnected", "recording_ready"]


# --- Signature verification -------------------------------------------------


# Cloudflare retries for ~24h with exponential backoff. 5 minutes is enough
# slack for clock skew + network without opening a meaningful replay window.
_REPLAY_WINDOW_SEC = 300


@dataclass(frozen=True)
class _ParsedSignature:
    time_sec: int
    sig: str


def _parse_signature_header(header: str) -> _ParsedSignature | None:
    """Parse `time=<unix>,sig1=<hex>`. Returns None on any parse error."""
    parts = [p.strip() for p in header.split(",") if p.strip()]
    fields: dict[str, str] = {}
    for p in parts:
        if "=" not in p:
            return None
        k, v = p.split("=", 1)
        fields[k.strip()] = v.strip()
    if "time" not in fields or "sig1" not in fields:
        return None
    try:
        ts = int(fields["time"])
    except ValueError:
        return None
    return _ParsedSignature(time_sec=ts, sig=fields["sig1"])


def verify_stream_webhook_signature(
    raw_body: bytes,
    header_value: str,
    secret: str,
    *,
    now_sec: int | None = None,
) -> bool:
    """Verify Cloudflare Stream's `Webhook-Signature` header.

    The signed string is `f"{time}.{body}"` (UTF-8 join, no separator on the
    body bytes — Cloudflare signs the raw bytes as received). Returns False if
    the secret is empty so a misconfigured deploy fails closed.
    """
    if not secret or not header_value:
        return False
    parsed = _parse_signature_header(header_value)
    if parsed is None:
        return False
    now = now_sec if now_sec is not None else int(time.time())
    if abs(now - parsed.time_sec) > _REPLAY_WINDOW_SEC:
        return False
    signed = str(parsed.time_sec).encode() + b"." + raw_body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parsed.sig)


# --- State machine ----------------------------------------------------------


@dataclass(frozen=True)
class TransitionResult:
    status_changed: bool
    recording_attached: bool


async def apply_live_input_event(
    db: AsyncSession,
    klass: Class,
    event_kind: EventKind,
    *,
    stream_client: StreamLiveClient,
    video_uid: str | None = None,
    now: datetime | None = None,
) -> TransitionResult:
    """Apply a normalized live-input event to a class. Idempotent.

    The caller is responsible for loading `klass` from the session — we mutate
    it in place and commit once. Returns a small result so callers can log.
    """
    now = now or datetime.now(UTC)
    settings = get_settings()
    grace = timedelta(minutes=settings.stream_end_grace_min)
    scheduled_end = klass.scheduled_start + timedelta(minutes=klass.duration_min)
    # SQLite (tests) drops tzinfo on round-trip; treat naive as UTC so the
    # comparison below doesn't blow up.
    if scheduled_end.tzinfo is None:
        scheduled_end = scheduled_end.replace(tzinfo=UTC)

    status_changed = False
    recording_attached = False

    if event_kind == "connected":
        # Late delivery after an admin already manually flipped status:
        # respect their choice for "ended", catch up for "scheduled".
        if klass.status == "scheduled":
            klass.status = "live"
            status_changed = True

    elif event_kind == "disconnected":
        if klass.status == "live" and now >= scheduled_end - grace:
            klass.status = "ended"
            status_changed = True
            if not klass.stream_video_uid and klass.stream_live_input_uid:
                attached_uid = await _safe_latest_recording_uid(
                    stream_client, klass.stream_live_input_uid
                )
                if attached_uid:
                    klass.stream_video_uid = attached_uid
                    recording_attached = True

    elif event_kind == "recording_ready":
        # Admin-set UID wins; webhooks for a never-attached class catch up.
        if video_uid and not klass.stream_video_uid:
            klass.stream_video_uid = video_uid
            recording_attached = True

    if status_changed or recording_attached:
        await db.commit()
        await db.refresh(klass)

    return TransitionResult(
        status_changed=status_changed, recording_attached=recording_attached
    )


async def _safe_latest_recording_uid(
    stream_client: StreamLiveClient, live_input_uid: str
) -> str | None:
    """Best-effort lookup. Failures are logged and treated as 'not ready yet';
    the dedicated `recording_ready` webhook and the cron sweep will retry."""
    try:
        status = await stream_client.get_status(live_input_uid)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "stream get_status failed during auto-attach for %s: %s",
            live_input_uid,
            exc,
        )
        return None
    return status.recording_video_uids[0] if status.recording_video_uids else None
