import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Class


@pytest.mark.asyncio
async def test_student_joins_free_class(client, session, test_user, cohort):
    klass = Class(
        id=uuid.uuid4(),
        title="Free class",
        scheduled_start=datetime.now(timezone.utc) + timedelta(hours=1),
        duration_min=60,
        access_type="free",
        cohort_id=cohort.id,
        stream_live_input_uid="fake-live-input-123",
    )
    session.add(klass)
    await session.commit()

    r = client.post(f"/classes/{klass.id}/join")
    assert r.status_code == 200, r.text
    body = r.json()
    # Signed HLS playback (Cloudflare Stream Live).
    assert body["hls_url"]
    assert body["iframe_url"]
    assert body["expires_at"]


@pytest.mark.asyncio
async def test_student_blocked_from_paid_class_without_entitlement(client, session, test_user, cohort):
    klass = Class(
        id=uuid.uuid4(),
        title="Paid class",
        scheduled_start=datetime.now(timezone.utc) + timedelta(hours=1),
        duration_min=60,
        access_type="paid",
        cohort_id=cohort.id,
        stream_live_input_uid="fake-live-input-456",
    )
    session.add(klass)
    await session.commit()

    r = client.post(f"/classes/{klass.id}/join")
    assert r.status_code == 403
