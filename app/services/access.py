"""The one access check. See section 1 of the plan."""

from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Class, Entitlement, RecordedLecture, User


async def can_access(db: AsyncSession, user: User, klass: Class) -> bool:
    if klass.access_type == "free":
        return True

    scope_clauses = [
        Entitlement.scope_type == "all_access",
        and_(Entitlement.scope_type == "class", Entitlement.scope_id == klass.id),
        and_(Entitlement.scope_type == "cohort", Entitlement.scope_id == klass.cohort_id),
    ]

    now = datetime.now(UTC)
    stmt = (
        select(Entitlement.id)
        .where(
            Entitlement.user_id == user.id,
            Entitlement.status == "active",
            or_(Entitlement.valid_until.is_(None), Entitlement.valid_until > now),
            or_(*scope_clauses),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def can_access_recorded(
    db: AsyncSession, user: User, lecture: RecordedLecture
) -> bool:
    """Same shape as can_access but for standalone recorded lectures.

    Paid recorded lectures grant access via cohort or all-access entitlements
    only — there's no per-lecture entitlement scope.
    """
    if lecture.access_type == "free":
        return True

    scope_clauses = [
        Entitlement.scope_type == "all_access",
        and_(
            Entitlement.scope_type == "recorded_lecture",
            Entitlement.scope_id == lecture.id,
        ),
        and_(Entitlement.scope_type == "cohort", Entitlement.scope_id == lecture.cohort_id),
    ]

    now = datetime.now(UTC)
    stmt = (
        select(Entitlement.id)
        .where(
            Entitlement.user_id == user.id,
            Entitlement.status == "active",
            or_(Entitlement.valid_until.is_(None), Entitlement.valid_until > now),
            or_(*scope_clauses),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None
