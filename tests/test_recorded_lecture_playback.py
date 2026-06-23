"""Student-facing playback for standalone recorded lectures."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models import Entitlement, RecordedLecture


def _lecture(cohort_id, **overrides) -> RecordedLecture:
    return RecordedLecture(
        id=uuid.uuid4(),
        title=overrides.pop("title", "Test lecture"),
        recorded_on=overrides.pop("recorded_on", datetime.now(UTC) - timedelta(days=1)),
        duration_min=overrides.pop("duration_min", 45),
        access_type=overrides.pop("access_type", "free"),
        cohort_id=cohort_id,
        stream_video_uid=overrides.pop("stream_video_uid", "vid-uid-1"),
        **overrides,
    )


@pytest.mark.asyncio
async def test_playback_free_anyone(client, session, cohort):
    lec = _lecture(cohort.id, access_type="free")
    session.add(lec)
    await session.commit()

    r = client.get(f"/lectures/{lec.id}/playback")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hls_url"]
    assert body["iframe_url"]


@pytest.mark.asyncio
async def test_playback_paid_blocked_without_entitlement(client, session, cohort):
    lec = _lecture(
        cohort.id, access_type="paid", price_single=Decimal("199.00"), stream_video_uid="v-2"
    )
    session.add(lec)
    await session.commit()

    r = client.get(f"/lectures/{lec.id}/playback")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_playback_paid_allowed_with_cohort_entitlement(
    client, session, test_user, cohort
):
    lec = _lecture(
        cohort.id, access_type="paid", price_single=Decimal("199.00"), stream_video_uid="v-3"
    )
    ent = Entitlement(
        id=uuid.uuid4(),
        user_id=test_user.id,
        scope_type="cohort",
        scope_id=cohort.id,
        source="cohort_enrollment",
        status="active",
    )
    session.add_all([lec, ent])
    await session.commit()

    r = client.get(f"/lectures/{lec.id}/playback")
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_playback_paid_allowed_with_all_access(client, session, test_user, cohort):
    lec = _lecture(
        cohort.id, access_type="paid", price_single=Decimal("199.00"), stream_video_uid="v-4"
    )
    ent = Entitlement(
        id=uuid.uuid4(),
        user_id=test_user.id,
        scope_type="all_access",
        scope_id=None,
        source="grant",
        status="active",
    )
    session.add_all([lec, ent])
    await session.commit()

    r = client.get(f"/lectures/{lec.id}/playback")
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_playback_404_when_lecture_missing(client):
    r = client.get(f"/lectures/{uuid.uuid4()}/playback")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_lectures_filters_by_cohort(client, session, cohort):
    from app.models import Cohort

    other = Cohort(id=uuid.uuid4(), title="Other cohort")
    session.add(other)
    a = _lecture(cohort.id, title="In cohort A")
    b = _lecture(other.id, title="In cohort B")
    session.add_all([a, b])
    await session.commit()

    r = client.get(f"/lectures?cohort_id={cohort.id}")
    assert r.status_code == 200
    titles = [row["title"] for row in r.json()]
    assert "In cohort A" in titles
    assert "In cohort B" not in titles


@pytest.mark.asyncio
async def test_get_lecture_detail(client, session, cohort):
    lec = _lecture(cohort.id, title="Detail check")
    session.add(lec)
    await session.commit()
    r = client.get(f"/lectures/{lec.id}")
    assert r.status_code == 200
    assert r.json()["title"] == "Detail check"
