"""Cloudflare Stream webhook + cron-poller behavior.

Covers signature verification (good, bad, expired), the connected /
disconnected / recording_ready state transitions on real DB rows, idempotency
(replay = no-op), and the cron fallback driving the same state machine via
`get_status()` instead of an inbound event.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Class
from app.services.stream_live import FakeStreamLiveClient, get_stream_live_client

WEBHOOK_SECRET = "test-stream-webhook-secret"  # mirrors conftest


def _sign(raw: bytes, t: int | None = None) -> tuple[str, bytes]:
    t = t if t is not None else int(time.time())
    signed = f"{t}.".encode() + raw
    sig = hmac.new(WEBHOOK_SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return f"time={t},sig1={sig}", raw


def _event(event_type: str, live_input_uid: str, video_uid: str | None = None) -> bytes:
    data: dict[str, object] = {"liveInputId": live_input_uid}
    if video_uid:
        data["videoId"] = video_uid
    return json.dumps({"eventType": event_type, "data": data}).encode()


def _class(cohort_id, *, status="scheduled", live_uid="li-fake", **overrides) -> Class:
    return Class(
        id=uuid.uuid4(),
        title=overrides.pop("title", "Webhook class"),
        scheduled_start=overrides.pop("scheduled_start", datetime.now(UTC)),
        duration_min=overrides.pop("duration_min", 60),
        access_type=overrides.pop("access_type", "free"),
        cohort_id=cohort_id,
        stream_live_input_uid=live_uid,
        status=status,
        **overrides,
    )


# --- Signature verification ---


@pytest.mark.asyncio
async def test_rejects_missing_signature(client, session, cohort):
    klass = _class(cohort.id)
    session.add(klass)
    await session.commit()

    raw = _event("live_input.connected", klass.stream_live_input_uid)
    r = client.post("/stream/webhook", content=raw, headers={"Content-Type": "application/json"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_rejects_bad_signature(client, session, cohort):
    klass = _class(cohort.id)
    session.add(klass)
    await session.commit()

    raw = _event("live_input.connected", klass.stream_live_input_uid)
    r = client.post(
        "/stream/webhook",
        content=raw,
        headers={"Webhook-Signature": "time=0,sig1=deadbeef", "Content-Type": "application/json"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_rejects_replay_outside_window(client, session, cohort):
    klass = _class(cohort.id)
    session.add(klass)
    await session.commit()

    raw = _event("live_input.connected", klass.stream_live_input_uid)
    old_ts = int(time.time()) - 3600  # 1h old, well outside 5min replay window
    header, _ = _sign(raw, t=old_ts)
    r = client.post(
        "/stream/webhook",
        content=raw,
        headers={"Webhook-Signature": header, "Content-Type": "application/json"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_bad_json_returns_400(client, session, cohort):
    raw = b"not-json"
    header, _ = _sign(raw)
    r = client.post(
        "/stream/webhook",
        content=raw,
        headers={"Webhook-Signature": header, "Content-Type": "application/json"},
    )
    assert r.status_code == 400


# --- State transitions ---


@pytest.mark.asyncio
async def test_connected_flips_scheduled_to_live(client, session, cohort):
    klass = _class(cohort.id, status="scheduled")
    session.add(klass)
    await session.commit()

    raw = _event("live_input.connected", klass.stream_live_input_uid)
    header, _ = _sign(raw)
    r = client.post(
        "/stream/webhook",
        content=raw,
        headers={"Webhook-Signature": header, "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status_changed"] is True

    await session.refresh(klass)
    assert klass.status == "live"


@pytest.mark.asyncio
async def test_connected_idempotent_when_already_live(client, session, cohort):
    klass = _class(cohort.id, status="live")
    session.add(klass)
    await session.commit()

    raw = _event("live_input.connected", klass.stream_live_input_uid)
    header, _ = _sign(raw)
    r = client.post(
        "/stream/webhook",
        content=raw,
        headers={"Webhook-Signature": header, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["status_changed"] is False
    await session.refresh(klass)
    assert klass.status == "live"


@pytest.mark.asyncio
async def test_disconnect_inside_window_stays_live(client, session, cohort):
    # Scheduled right now, 60 min long -> disconnect at t+0 is *inside* the
    # window, so we should NOT mark ended (transient encoder hiccup).
    klass = _class(
        cohort.id,
        status="live",
        scheduled_start=datetime.now(UTC),
        duration_min=60,
    )
    session.add(klass)
    await session.commit()

    raw = _event("live_input.disconnected", klass.stream_live_input_uid)
    header, _ = _sign(raw)
    r = client.post(
        "/stream/webhook",
        content=raw,
        headers={"Webhook-Signature": header, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["status_changed"] is False
    await session.refresh(klass)
    assert klass.status == "live"


@pytest.mark.asyncio
async def test_disconnect_past_grace_marks_ended_and_auto_attaches(
    client, session, cohort
):
    # Scheduled 2h ago, 60 min long -> we're well past scheduled_end - 5min.
    klass = _class(
        cohort.id,
        status="live",
        scheduled_start=datetime.now(UTC) - timedelta(hours=2),
        duration_min=60,
        live_uid="li-attach-test",
    )
    session.add(klass)
    await session.commit()

    raw = _event("live_input.disconnected", klass.stream_live_input_uid)
    header, _ = _sign(raw)
    r = client.post(
        "/stream/webhook",
        content=raw,
        headers={"Webhook-Signature": header, "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status_changed"] is True
    assert body["recording_attached"] is True

    await session.refresh(klass)
    assert klass.status == "ended"
    # FakeStreamLiveClient.get_status returns recording_video_uids=[f"rec-{uid[:12]}"]
    assert klass.stream_video_uid and klass.stream_video_uid.startswith("rec-")


@pytest.mark.asyncio
async def test_recording_ready_sets_uid(client, session, cohort):
    klass = _class(cohort.id, status="ended")
    session.add(klass)
    await session.commit()

    raw = _event(
        "live_input.live_recording.ready",
        klass.stream_live_input_uid,
        video_uid="vid-fresh-123",
    )
    header, _ = _sign(raw)
    r = client.post(
        "/stream/webhook",
        content=raw,
        headers={"Webhook-Signature": header, "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["recording_attached"] is True

    await session.refresh(klass)
    assert klass.stream_video_uid == "vid-fresh-123"


@pytest.mark.asyncio
async def test_recording_ready_does_not_overwrite_admin_uid(client, session, cohort):
    klass = _class(cohort.id, status="ended", stream_video_uid="admin-set-uid")
    session.add(klass)
    await session.commit()

    raw = _event(
        "live_input.live_recording.ready",
        klass.stream_live_input_uid,
        video_uid="webhook-uid",
    )
    header, _ = _sign(raw)
    r = client.post(
        "/stream/webhook",
        content=raw,
        headers={"Webhook-Signature": header, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["recording_attached"] is False

    await session.refresh(klass)
    assert klass.stream_video_uid == "admin-set-uid"


@pytest.mark.asyncio
async def test_unknown_event_type_ignored_200(client, session, cohort):
    klass = _class(cohort.id)
    session.add(klass)
    await session.commit()

    raw = json.dumps(
        {"eventType": "video.something_new", "data": {"liveInputId": klass.stream_live_input_uid}}
    ).encode()
    header, _ = _sign(raw)
    r = client.post(
        "/stream/webhook",
        content=raw,
        headers={"Webhook-Signature": header, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json().get("ignored") is True
    await session.refresh(klass)
    assert klass.status == "scheduled"


@pytest.mark.asyncio
async def test_orphan_live_input_ignored_200(client):
    raw = _event("live_input.connected", "li-nobody-owns")
    header, _ = _sign(raw)
    r = client.post(
        "/stream/webhook",
        content=raw,
        headers={"Webhook-Signature": header, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json().get("ignored") is True


# --- Cron fallback ---


class _ConnectedStreamClient(FakeStreamLiveClient):
    """Reports the live input as currently connected, so the cron poller
    should flip scheduled → live."""

    async def get_status(self, uid: str):  # type: ignore[override]
        from app.services.stream_live import LiveInputStatus

        return LiveInputStatus(uid=uid, connected=True, recording_video_uids=[])


class _DisconnectedWithRecordingClient(FakeStreamLiveClient):
    async def get_status(self, uid: str):  # type: ignore[override]
        from app.services.stream_live import LiveInputStatus

        return LiveInputStatus(
            uid=uid, connected=False, recording_video_uids=[f"rec-cron-{uid[:6]}"]
        )


@pytest.mark.asyncio
async def test_cron_sync_flips_scheduled_to_live_when_connected(client, session, cohort):
    from app.main import app

    klass = _class(
        cohort.id,
        status="scheduled",
        scheduled_start=datetime.now(UTC),
        duration_min=60,
    )
    session.add(klass)
    await session.commit()

    app.dependency_overrides[get_stream_live_client] = lambda: _ConnectedStreamClient()
    try:
        r = client.post(
            "/cron/sync-class-statuses",
            headers={"X-Cron-Token": "dev"},
        )
    finally:
        app.dependency_overrides.pop(get_stream_live_client, None)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["checked"] >= 1
    assert body["transitioned"] >= 1

    await session.refresh(klass)
    assert klass.status == "live"


@pytest.mark.asyncio
async def test_cron_sync_ends_live_class_and_attaches_recording(client, session, cohort):
    from app.main import app

    # Live class, scheduled 90 min ago + 60 min duration -> ended 30 min ago,
    # but still inside the cron's ±2h reconciliation window.
    klass = _class(
        cohort.id,
        status="live",
        scheduled_start=datetime.now(UTC) - timedelta(minutes=90),
        duration_min=60,
        live_uid="li-cron-attach",
    )
    session.add(klass)
    await session.commit()

    app.dependency_overrides[get_stream_live_client] = lambda: _DisconnectedWithRecordingClient()
    try:
        r = client.post(
            "/cron/sync-class-statuses",
            headers={"X-Cron-Token": "dev"},
        )
    finally:
        app.dependency_overrides.pop(get_stream_live_client, None)

    assert r.status_code == 200, r.text

    await session.refresh(klass)
    assert klass.status == "ended"
    assert klass.stream_video_uid and klass.stream_video_uid.startswith("rec-")


@pytest.mark.asyncio
async def test_cron_sync_requires_token(client):
    r = client.post("/cron/sync-class-statuses")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_cron_sync_ignores_classes_far_outside_window(client, session, cohort):
    # A class 1 week from now should not be polled.
    klass = _class(
        cohort.id,
        status="scheduled",
        scheduled_start=datetime.now(UTC) + timedelta(days=7),
        duration_min=60,
    )
    session.add(klass)
    await session.commit()

    r = client.post("/cron/sync-class-statuses", headers={"X-Cron-Token": "dev"})
    assert r.status_code == 200
    # Only count behavior we care about: this class wasn't acted on.
    await session.refresh(klass)
    assert klass.status == "scheduled"


@pytest.mark.asyncio
async def test_stream_webhook_disabled_when_secret_missing(client, session, cohort, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "cloudflare_stream_webhook_secret", "")

    klass = _class(cohort.id)
    session.add(klass)
    await session.commit()

    raw = _event("live_input.connected", klass.stream_live_input_uid)
    header, _ = _sign(raw)  # signed with the real secret, but server will refuse outright
    r = client.post(
        "/stream/webhook",
        content=raw,
        headers={"Webhook-Signature": header, "Content-Type": "application/json"},
    )
    assert r.status_code == 503
