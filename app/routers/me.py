from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.db import get_db
from app.models import Entitlement, User
from app.schemas import EntitlementOut, ProfileUpdateIn, ProfileUpdateOut, UserOut
from app.services.session import issue_session_jwt

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=UserOut)
async def get_me(user: User = Depends(current_user)) -> User:
    return user


@router.patch("", response_model=ProfileUpdateOut)
async def update_me(
    body: ProfileUpdateIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileUpdateOut:
    user = await db.get(User, user.id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    updates = body.model_dump(exclude_unset=True)
    for field in ("name", "target_exam", "grade"):
        if field in updates:
            setattr(user, field, updates[field])

    if body.accept_terms and user.terms_accepted_at is None:
        user.terms_accepted_at = datetime.now(UTC)
        user.consent_version = body.consent_version

    await db.commit()
    await db.refresh(user)
    token, expires_at = issue_session_jwt(
        user.id,
        user.email,
        user.role,
        name=user.name,
        phone=user.phone,
    )
    return ProfileUpdateOut(user=user, access_token=token, expires_at=expires_at)


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
