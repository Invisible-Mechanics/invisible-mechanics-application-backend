import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.db import get_db
from app.models import Class, Cohort, User
from app.schemas import (
    AdminUserCreate,
    AdminUserRow,
    AdminUserRoleUpdate,
    AdminClassOut,
    ClassCreate,
    ClassStatusUpdate,
    ClassUpdate,
    CohortCreate,
    CohortOut,
    CohortUpdate,
    RecordingAttach,
    StreamKeysOut,
    UserOut,
)
from app.services.stream_live import StreamLiveClient, get_stream_live_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ---------- User admin ----------


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    body: AdminUserCreate,
    db: AsyncSession = Depends(get_db),
) -> User:
    existing = (
        await db.execute(select(User).where(User.email == str(body.email).strip().lower()))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="user already exists")
    user = User(
        email=str(body.email).strip().lower(),
        name=body.name,
        phone=body.phone,
        role=body.role,
        source="admin",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/users", response_model=list[AdminUserRow])
async def list_users(
    q: str = "",
    db: AsyncSession = Depends(get_db),
) -> list[User]:
    stmt = select(User).order_by(User.created_at.desc()).limit(50)
    needle = q.strip()
    if needle:
        like = f"%{needle.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.email).like(like),
                func.lower(func.coalesce(User.name, "")).like(like),
                func.coalesce(User.phone, "").like(f"%{needle}%"),
            )
        )
    return list((await db.execute(stmt)).scalars().all())


@router.patch("/users/{user_id}/role", response_model=UserOut)
async def update_user_role(
    user_id: uuid.UUID,
    body: AdminUserRoleUpdate,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    user.role = body.role
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/classes", response_model=AdminClassOut, status_code=201)
async def create_class(
    body: ClassCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
    stream: StreamLiveClient = Depends(get_stream_live_client),
) -> Class:
    if await db.get(Cohort, body.cohort_id) is None:
        raise HTTPException(status_code=400, detail="cohort not found")

    live = await stream.create_live_input(name=body.title)
    klass = Class(
        title=body.title,
        description=body.description,
        subject=body.subject,
        topic=body.topic,
        scheduled_start=body.scheduled_start,
        duration_min=body.duration_min,
        access_type=body.access_type,
        cohort_id=body.cohort_id,
        price_single=body.price_single,
        thumbnail_url=body.thumbnail_url,
        target_exam=body.target_exam,
        target_year=body.target_year,
        stream_live_input_uid=live.uid,
        status="scheduled",
    )
    db.add(klass)
    await db.commit()
    await db.refresh(klass)
    return klass


@router.get("/classes/{class_id}", response_model=AdminClassOut)
async def get_admin_class(class_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Class:
    klass = await db.get(Class, class_id)
    if klass is None:
        raise HTTPException(status_code=404, detail="lecture not found")
    return klass


@router.patch("/classes/{class_id}/status", response_model=AdminClassOut)
async def update_class_status(
    class_id: uuid.UUID,
    body: ClassStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> Class:
    klass = await db.get(Class, class_id)
    if klass is None:
        raise HTTPException(status_code=404, detail="lecture not found")
    klass.status = body.status
    await db.commit()
    await db.refresh(klass)
    return klass


@router.patch("/classes/{class_id}", response_model=AdminClassOut)
async def update_class(
    class_id: uuid.UUID,
    body: ClassUpdate,
    db: AsyncSession = Depends(get_db),
) -> Class:
    klass = await db.get(Class, class_id)
    if klass is None:
        raise HTTPException(status_code=404, detail="lecture not found")
    updates = body.model_dump(exclude_unset=True)
    if "cohort_id" in updates:
        if updates["cohort_id"] is None:
            raise HTTPException(status_code=400, detail="cohort_id is required")
        if await db.get(Cohort, updates["cohort_id"]) is None:
            raise HTTPException(status_code=400, detail="cohort not found")
    for field, value in updates.items():
        setattr(klass, field, value)
    await db.commit()
    await db.refresh(klass)
    return klass


@router.delete("/classes/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_class(
    class_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    stream: StreamLiveClient = Depends(get_stream_live_client),
) -> Response:
    klass = await db.get(Class, class_id)
    if klass is None:
        raise HTTPException(status_code=404, detail="lecture not found")

    if klass.stream_live_input_uid:
        try:
            await stream.delete_live_input(klass.stream_live_input_uid)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "stream live input delete failed for %s: %s",
                klass.stream_live_input_uid,
                e,
            )

    await db.delete(klass)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/classes/{class_id}/stream-keys", response_model=StreamKeysOut)
async def get_stream_keys(
    class_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    stream: StreamLiveClient = Depends(get_stream_live_client),
) -> StreamKeysOut:
    """Return the RTMPS push credentials the instructor pastes into OBS."""
    klass = await db.get(Class, class_id)
    if klass is None:
        raise HTTPException(status_code=404, detail="lecture not found")
    if not klass.stream_live_input_uid:
        raise HTTPException(status_code=409, detail="lecture has no Stream live input")
    keys = await stream.get_keys(klass.stream_live_input_uid)
    return StreamKeysOut(
        rtmps_url=keys.rtmps_url,
        rtmps_stream_key=keys.rtmps_stream_key,
        live_input_uid=keys.uid,
    )


# ---------- Cohort admin ----------


@router.post("/cohorts", response_model=CohortOut, status_code=201)
async def create_cohort(
    body: CohortCreate,
    db: AsyncSession = Depends(get_db),
) -> Cohort:
    cohort = Cohort(**body.model_dump())
    db.add(cohort)
    await db.commit()
    await db.refresh(cohort)
    return cohort


@router.patch("/cohorts/{cohort_id}", response_model=CohortOut)
async def update_cohort(
    cohort_id: uuid.UUID,
    body: CohortUpdate,
    db: AsyncSession = Depends(get_db),
) -> Cohort:
    cohort = await db.get(Cohort, cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="cohort not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(cohort, field, value)
    await db.commit()
    await db.refresh(cohort)
    return cohort


@router.delete("/cohorts/{cohort_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cohort(
    cohort_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    cohort = await db.get(Cohort, cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="cohort not found")
    # Classes are now required to belong to a cohort, so cohort deletion can
    # no longer orphan them. Refuse if any classes still reference this cohort
    # — admin moves or deletes them first.
    attached = (
        await db.execute(
            select(func.count()).select_from(Class).where(Class.cohort_id == cohort_id)
        )
    ).scalar_one()
    if attached:
        raise HTTPException(
            status_code=409,
            detail=f"cohort has {attached} attached lecture(s); move or delete them first",
        )
    await db.delete(cohort)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- Recording admin (live classes) ----------


@router.put("/classes/{class_id}/recording", response_model=AdminClassOut)
async def attach_recording(
    class_id: uuid.UUID,
    body: RecordingAttach,
    db: AsyncSession = Depends(get_db),
) -> Class:
    """Attach (or replace) the post-broadcast Cloudflare Stream recording UID."""
    klass = await db.get(Class, class_id)
    if klass is None:
        raise HTTPException(status_code=404, detail="lecture not found")
    klass.stream_video_uid = body.stream_video_uid
    await db.commit()
    await db.refresh(klass)
    return klass


@router.post(
    "/classes/{class_id}/recording/attach-from-live-input",
    response_model=AdminClassOut,
)
async def attach_recording_from_live_input(
    class_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    stream: StreamLiveClient = Depends(get_stream_live_client),
) -> Class:
    """Auto-attach the most recent Cloudflare Stream recording for this class.

    Saves admins from copy-pasting a UID after each broadcast: we ask Stream
    for the live input's recorded videos and store the newest one.
    """
    klass = await db.get(Class, class_id)
    if klass is None:
        raise HTTPException(status_code=404, detail="lecture not found")
    if not klass.stream_live_input_uid:
        raise HTTPException(status_code=409, detail="lecture has no Stream live input")

    status_info = await stream.get_status(klass.stream_live_input_uid)
    if not status_info.recording_video_uids:
        raise HTTPException(status_code=409, detail="no recordings yet for this live input")
    # Newest-first ordering depends on the upstream API; the Cloudflare list
    # returns videos sorted by creation desc by default. Take the first UID.
    klass.stream_video_uid = status_info.recording_video_uids[0]
    await db.commit()
    await db.refresh(klass)
    return klass


@router.delete("/classes/{class_id}/recording", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recording(
    class_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    klass = await db.get(Class, class_id)
    if klass is None:
        raise HTTPException(status_code=404, detail="lecture not found")
    if klass.stream_video_uid is None:
        raise HTTPException(status_code=404, detail="no recording attached")
    klass.stream_video_uid = None
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
