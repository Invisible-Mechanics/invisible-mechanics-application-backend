import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Entitlement


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
