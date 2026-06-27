from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user, require_admin
from app.db import get_db
from app.models import MasterclassEvent, User
from app.schemas import (
    MasterclassEventAdminOut,
    MasterclassEventCreate,
    MasterclassEventOut,
    MasterclassEventSummaryOut,
)
from app.services.enrollment_notifications import (
    send_masterclass_enrollment_notification_best_effort,
)

router = APIRouter(prefix="/masterclass", tags=["masterclass"])
admin_router = APIRouter(prefix="/admin/masterclass", tags=["admin", "masterclass"])


@router.post("/events", response_model=MasterclassEventOut, status_code=201)
async def track_masterclass_event(
    body: MasterclassEventCreate,
    user_agent: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> MasterclassEvent:
    if body.event_type == "registration_completed":
        raise HTTPException(status_code=401, detail="registration completion requires auth")
    event = MasterclassEvent(
        visitor_id=body.visitor_id,
        event_type=body.event_type,
        source=body.source,
        path=body.path,
        user_agent=user_agent,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


@router.post("/events/registration-completed", response_model=MasterclassEventOut, status_code=201)
async def track_masterclass_registration_completed(
    body: MasterclassEventCreate,
    user_agent: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> MasterclassEvent:
    event = MasterclassEvent(
        visitor_id=body.visitor_id,
        user_id=user.id,
        event_type="registration_completed",
        source=body.source,
        path=body.path,
        user_agent=user_agent,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    await send_masterclass_enrollment_notification_best_effort(user)
    return event


@admin_router.get("/events", response_model=list[MasterclassEventAdminOut])
async def list_masterclass_events(
    event_type: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[MasterclassEventAdminOut]:
    stmt = (
        select(MasterclassEvent, User)
        .outerjoin(User, MasterclassEvent.user_id == User.id)
        .order_by(MasterclassEvent.created_at.desc())
        .limit(limit)
    )
    if event_type:
        stmt = stmt.where(MasterclassEvent.event_type == event_type)
    rows = (await db.execute(stmt)).all()
    return [
        MasterclassEventAdminOut(
            id=event.id,
            visitor_id=event.visitor_id,
            user_id=event.user_id,
            event_type=event.event_type,
            source=event.source,
            path=event.path,
            user_agent=event.user_agent,
            created_at=event.created_at,
            user_email=user.email if user else None,
            user_name=user.name if user else None,
            user_phone=user.phone if user else None,
        )
        for event, user in rows
    ]


@admin_router.get("/summary", response_model=MasterclassEventSummaryOut)
async def masterclass_summary(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> MasterclassEventSummaryOut:
    rows = (
        await db.execute(
            select(MasterclassEvent.event_type, func.count())
            .where(
                MasterclassEvent.event_type.in_(
                    ["enroll_now_clicked", "registration_completed"]
                )
            )
            .group_by(MasterclassEvent.event_type)
        )
    ).all()
    counts = {str(event_type): int(count) for event_type, count in rows}
    return MasterclassEventSummaryOut(
        enroll_now_clicked=counts.get("enroll_now_clicked", 0),
        registration_completed=counts.get("registration_completed", 0),
    )
