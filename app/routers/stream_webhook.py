"""Cloudflare Stream webhook receiver.

Mirrors the unauthenticated `enrollments.webhook_router` shape — auth is
the HMAC signature on the body, verified against
`CLOUDFLARE_STREAM_WEBHOOK_SECRET`.

We always return 200 for *known-shaped* events (dispatched or ignored) so
Cloudflare stops retrying. Bad signatures and bad JSON are the only 4xx —
they indicate a misconfig, not a transient failure.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import Class
from app.services.stream_live import StreamLiveClient, get_stream_live_client
from app.services.stream_webhook import (
    EventKind,
    apply_live_input_event,
    verify_stream_webhook_signature,
)

logger = logging.getLogger(__name__)

webhook_router = APIRouter(tags=["webhooks"])


# Cloudflare Stream `eventType` values we act on. Anything else is logged and
# acknowledged with 200 so a new CF event type doesn't break us.
_EVENT_KIND_MAP: dict[str, EventKind] = {
    "live_input.connected": "connected",
    "live_input.disconnected": "disconnected",
    "live_input.live_recording.ready": "recording_ready",
}


@webhook_router.post("/stream/webhook")
async def cloudflare_stream_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    stream: StreamLiveClient = Depends(get_stream_live_client),
) -> dict:
    raw = await request.body()
    signature = request.headers.get("Webhook-Signature", "")

    secret = get_settings().cloudflare_stream_webhook_secret
    if not secret:
        # Webhook ingestion is off — the cron poller is the fallback. Reject
        # so an accidentally-public endpoint doesn't quietly accept events.
        raise HTTPException(status_code=503, detail="stream webhook not configured")

    if not verify_stream_webhook_signature(raw, signature, secret):
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid json body")

    event_type = event.get("eventType") or event.get("event")
    kind = _EVENT_KIND_MAP.get(event_type or "")
    if kind is None:
        logger.info("stream webhook: ignoring eventType=%r", event_type)
        return {"ok": True, "ignored": True, "reason": "unknown event type"}

    data = event.get("data") or {}
    live_input_uid = (
        data.get("liveInputId")
        or data.get("live_input_id")
        or data.get("input_id")
    )
    if not live_input_uid:
        logger.warning("stream webhook: %s missing liveInputId", event_type)
        return {"ok": True, "ignored": True, "reason": "missing liveInputId"}

    klass = (
        await db.execute(
            select(Class).where(Class.stream_live_input_uid == live_input_uid)
        )
    ).scalar_one_or_none()
    if klass is None:
        # Orphaned live input (manual test, or a class we already deleted).
        # 200 so CF stops retrying.
        logger.info(
            "stream webhook: no class for liveInputId=%s, ignoring", live_input_uid
        )
        return {"ok": True, "ignored": True, "reason": "no matching class"}

    video_uid = data.get("videoId") or data.get("video_id") if kind == "recording_ready" else None

    result = await apply_live_input_event(
        db,
        klass,
        kind,
        stream_client=stream,
        video_uid=video_uid,
    )

    return {
        "ok": True,
        "class_id": str(klass.id),
        "event": kind,
        "status_changed": result.status_changed,
        "recording_attached": result.recording_attached,
    }
