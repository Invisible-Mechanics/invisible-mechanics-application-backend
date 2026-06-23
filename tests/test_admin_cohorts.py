import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Class, Cohort


@pytest.mark.asyncio
async def test_admin_can_create_cohort(admin_client):
    r = admin_client.post(
        "/admin/cohorts",
        json={
            "title": "JEE Physics — Summer 2026",
            "description": "Full syllabus over 12 weeks.",
            "price": "9999.00",
            "seat_limit": 50,
            "start_date": "2026-06-15",
            "end_date": "2026-09-15",
            "status": "open",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "JEE Physics — Summer 2026"
    assert body["seat_limit"] == 50
    assert body["status"] == "open"
    assert body["seats_taken"] == 0


@pytest.mark.asyncio
async def test_admin_can_patch_cohort(admin_client, session):
    cohort = Cohort(
        id=uuid.uuid4(),
        title="Original",
        seat_limit=30,
        status="open",
    )
    session.add(cohort)
    await session.commit()

    r = admin_client.patch(
        f"/admin/cohorts/{cohort.id}",
        json={"title": "Renamed", "seat_limit": 60},
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Renamed"
    assert r.json()["seat_limit"] == 60
    assert r.json()["status"] == "open"  # untouched


@pytest.mark.asyncio
async def test_delete_cohort_with_attached_classes_returns_409(admin_client, session):
    cohort = Cohort(id=uuid.uuid4(), title="To delete", status="open")
    klass = Class(
        id=uuid.uuid4(),
        title="Attached class",
        scheduled_start=datetime.now(timezone.utc) + timedelta(days=1),
        duration_min=60,
        access_type="free",
        cohort_id=cohort.id,
    )
    session.add_all([cohort, klass])
    await session.commit()

    # Classes are required to belong to a cohort — cohort deletion is blocked
    # while any class still references it. Admin moves or deletes them first.
    r = admin_client.delete(f"/admin/cohorts/{cohort.id}")
    assert r.status_code == 409
    assert "attached" in r.json()["detail"]


@pytest.mark.asyncio
async def test_delete_empty_cohort_succeeds(admin_client, session):
    cohort = Cohort(id=uuid.uuid4(), title="Empty", status="open")
    session.add(cohort)
    await session.commit()

    r = admin_client.delete(f"/admin/cohorts/{cohort.id}")
    assert r.status_code == 204


def test_patch_unknown_cohort_returns_404(admin_client):
    r = admin_client.patch(f"/admin/cohorts/{uuid.uuid4()}", json={"title": "x"})
    assert r.status_code == 404


def test_delete_unknown_cohort_returns_404(admin_client):
    r = admin_client.delete(f"/admin/cohorts/{uuid.uuid4()}")
    assert r.status_code == 404
