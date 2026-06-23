"""Recording attach + playback flow, now folded into the Class model.

A Class with stream_video_uid set is playable via /classes/{id}/recording.
Admin attaches the UID either manually (PUT /admin/classes/{id}/recording)
or by asking Cloudflare for the latest video from the live input
(POST /admin/classes/{id}/recording/attach-from-live-input).
"""
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models import Class, Entitlement


def _class(cohort_id, **overrides) -> Class:
    return Class(
        id=uuid.uuid4(),
        title=overrides.pop("title", "Recorded class"),
        scheduled_start=datetime.now(UTC) - timedelta(days=1),
        duration_min=60,
        access_type=overrides.pop("access_type", "free"),
        cohort_id=cohort_id,
        **overrides,
    )


# ---------- Admin ----------


@pytest.mark.asyncio
async def test_admin_attach_recording_by_stream_uid(admin_client, session, cohort):
    klass = _class(cohort.id)
    session.add(klass)
    await session.commit()

    r = admin_client.put(
        f"/admin/classes/{klass.id}/recording",
        json={"stream_video_uid": "abcdef0123456789"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["stream_video_uid"] == "abcdef0123456789"


@pytest.mark.asyncio
async def test_admin_reattach_replaces_uid(admin_client, session, cohort):
    klass = _class(cohort.id)
    session.add(klass)
    await session.commit()

    admin_client.put(
        f"/admin/classes/{klass.id}/recording",
        json={"stream_video_uid": "uid-one"},
    )
    admin_client.put(
        f"/admin/classes/{klass.id}/recording",
        json={"stream_video_uid": "uid-two"},
    )
    await session.refresh(klass)
    assert klass.stream_video_uid == "uid-two"


@pytest.mark.asyncio
async def test_admin_attach_from_live_input(admin_client, session, cohort):
    """When the live input has produced a recording, admin can attach without
    pasting the UID by hand — the backend asks Cloudflare for the latest video."""
    klass = _class(cohort.id, stream_live_input_uid="fake-live-input-99")
    session.add(klass)
    await session.commit()

    r = admin_client.post(f"/admin/classes/{klass.id}/recording/attach-from-live-input")
    assert r.status_code == 200, r.text
    assert r.json()["stream_video_uid"]


@pytest.mark.asyncio
async def test_admin_attach_from_live_input_requires_live_input(admin_client, session, cohort):
    # Classes that haven't been provisioned with a live input yet can't auto-attach.
    klass = _class(cohort.id, stream_live_input_uid=None, stream_video_uid="original-uid")
    session.add(klass)
    await session.commit()

    r = admin_client.post(f"/admin/classes/{klass.id}/recording/attach-from-live-input")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_admin_delete_recording(admin_client, session, cohort):
    klass = _class(cohort.id, stream_video_uid="some-uid")
    session.add(klass)
    await session.commit()

    assert admin_client.delete(f"/admin/classes/{klass.id}/recording").status_code == 204
    await session.refresh(klass)
    assert klass.stream_video_uid is None


# ---------- Student playback ----------


@pytest.mark.asyncio
async def test_playback_free_class_anyone(client, session, cohort):
    klass = _class(cohort.id, access_type="free", stream_video_uid="vid-1")
    session.add(klass)
    await session.commit()

    r = client.get(f"/classes/{klass.id}/recording")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hls_url"]
    assert body["iframe_url"]


@pytest.mark.asyncio
async def test_playback_paid_blocked_without_entitlement(client, session, cohort):
    klass = _class(
        cohort.id, access_type="paid", price_single=Decimal("499.00"), stream_video_uid="vid-2"
    )
    session.add(klass)
    await session.commit()

    r = client.get(f"/classes/{klass.id}/recording")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_playback_paid_allowed_with_class_entitlement(client, session, test_user, cohort):
    klass = _class(
        cohort.id, access_type="paid", price_single=Decimal("499.00"), stream_video_uid="vid-3"
    )
    ent = Entitlement(
        id=uuid.uuid4(),
        user_id=test_user.id,
        scope_type="class",
        scope_id=klass.id,
        source="razorpay",
        status="active",
    )
    session.add_all([klass, ent])
    await session.commit()

    r = client.get(f"/classes/{klass.id}/recording")
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_playback_paid_allowed_with_cohort_entitlement(client, session, test_user, cohort):
    klass = _class(
        cohort.id, access_type="paid", price_single=Decimal("499.00"), stream_video_uid="vid-4"
    )
    ent = Entitlement(
        id=uuid.uuid4(),
        user_id=test_user.id,
        scope_type="cohort",
        scope_id=cohort.id,
        source="cohort_enrollment",
        status="active",
    )
    session.add_all([klass, ent])
    await session.commit()

    r = client.get(f"/classes/{klass.id}/recording")
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_playback_no_recording_404(client, session, cohort):
    klass = _class(cohort.id, access_type="free")
    session.add(klass)
    await session.commit()
    r = client.get(f"/classes/{klass.id}/recording")
    assert r.status_code == 404
