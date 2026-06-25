import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import Entitlement, User


@pytest.mark.asyncio
async def test_me_entitlements_empty(client, test_user):
    r = client.get("/me/entitlements")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_me_entitlements_returns_active(client, session, test_user):
    cohort_id = uuid.uuid4()
    ent = Entitlement(
        id=uuid.uuid4(),
        user_id=test_user.id,
        scope_type="cohort",
        scope_id=cohort_id,
        source="cohort_enrollment",
        valid_until=datetime.now(timezone.utc) + timedelta(days=30),
        status="active",
    )
    session.add(ent)
    await session.commit()

    r = client.get("/me/entitlements")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["scope_type"] == "cohort"
    assert body[0]["scope_id"] == str(cohort_id)


@pytest.mark.asyncio
async def test_me_entitlements_excludes_expired(client, session, test_user):
    ent = Entitlement(
        id=uuid.uuid4(),
        user_id=test_user.id,
        scope_type="all_access",
        scope_id=None,
        source="subscription",
        valid_until=datetime.now(timezone.utc) - timedelta(days=1),
        status="active",
    )
    session.add(ent)
    await session.commit()

    r = client.get("/me/entitlements")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_profile_update_records_student_details_and_consent(client, session, test_user):
    user_id = test_user.id
    r = client.patch(
        "/me",
        json={
            "name": "Ritank",
            "target_exam": "jee",
            "grade": "12",
            "accept_terms": True,
            "consent_version": "25 June 2026",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["user"]["name"] == "Ritank"
    assert body["user"]["target_exam"] == "jee"
    assert body["user"]["grade"] == "12"
    assert body["user"]["terms_accepted_at"] is not None

    session.expire_all()
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
    assert user.consent_version == "25 June 2026"


@pytest.mark.asyncio
async def test_profile_consent_is_idempotent(client, session, test_user):
    user_id = test_user.id
    first = client.patch(
        "/me",
        json={
            "name": "Student",
            "target_exam": "neet",
            "grade": "11",
            "accept_terms": True,
            "consent_version": "25 June 2026",
        },
    )
    assert first.status_code == 200, first.text
    first_terms_at = first.json()["user"]["terms_accepted_at"]

    second = client.patch(
        "/me",
        json={
            "name": "Student Updated",
            "target_exam": "neet",
            "grade": "12",
            "accept_terms": True,
            "consent_version": "changed-version",
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["user"]["terms_accepted_at"] == first_terms_at

    session.expire_all()
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
    assert user.name == "Student Updated"
    assert user.grade == "12"
    assert user.consent_version == "25 June 2026"
