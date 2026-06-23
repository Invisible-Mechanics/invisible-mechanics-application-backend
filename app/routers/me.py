from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.db import get_db
from app.models import Entitlement, User
from app.schemas import EntitlementOut, UserOut

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=UserOut)
async def get_me(user: User = Depends(current_user)) -> User:
    return user


@router.get("/entitlements", response_model=list[EntitlementOut])
async def list_my_entitlements(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Entitlement]:
    now = datetime.now(UTC)
    stmt = (
        select(Entitlement)
        .where(
            Entitlement.user_id == user.id,
            Entitlement.status == "active",
            or_(Entitlement.valid_until.is_(None), Entitlement.valid_until > now),
        )
        .order_by(Entitlement.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())
