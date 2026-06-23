import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Class


async def _seed_class(session, cohort) -> Class:
    klass = Class(
        id=uuid.uuid4(),
        title="Original title",
        scheduled_start=datetime.now(timezone.utc) + timedelta(days=1),
        duration_min=60,
        access_type="free",
        cohort_id=cohort.id,
        status="scheduled",
        stream_live_input_uid="fake-live-input-x",
    )
    session.add(klass)
    await session.commit()
    await session.refresh(klass)
    return klass


@pytest.mark.asyncio
async def test_admin_can_patch_class(admin_client, session, cohort):
    klass = await _seed_class(session, cohort)

    r = admin_client.patch(
        f"/admin/classes/{klass.id}",
        json={
            "title": "Updated title",
            "target_exam": "jee",
            "target_year": 2027,
            "thumbnail_url": "https://example.com/t.jpg",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Updated title"
    assert body["target_exam"] == "jee"
    assert body["target_year"] == 2027
    assert body["thumbnail_url"] == "https://example.com/t.jpg"
    # Untouched fields preserved
    assert body["duration_min"] == 60
    assert body["access_type"] == "free"


@pytest.mark.asyncio
async def test_patch_can_clear_thumbnail(admin_client, session, cohort):
    klass = await _seed_class(session, cohort)
    klass.thumbnail_url = "https://example.com/old.jpg"
    await session.commit()

    r = admin_client.patch(f"/admin/classes/{klass.id}", json={"thumbnail_url": None})
    assert r.status_code == 200
    assert r.json()["thumbnail_url"] is None


@pytest.mark.asyncio
async def test_admin_can_delete_class(admin_client, session, cohort):
    klass = await _seed_class(session, cohort)

    r = admin_client.delete(f"/admin/classes/{klass.id}")
    assert r.status_code == 204

    r2 = admin_client.get(f"/classes/{klass.id}")
    assert r2.status_code == 404


def test_patch_unknown_class_returns_404(admin_client):
    r = admin_client.patch(f"/admin/classes/{uuid.uuid4()}", json={"title": "x"})
    assert r.status_code == 404


def test_delete_unknown_class_returns_404(admin_client):
    r = admin_client.delete(f"/admin/classes/{uuid.uuid4()}")
    assert r.status_code == 404
