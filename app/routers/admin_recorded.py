import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.db import get_db
from app.models import Cohort, RecordedLecture, User
from app.schemas import (
    RecordedLectureCreate,
    RecordedLectureOut,
    RecordedLectureUpdate,
)

router = APIRouter(
    prefix="/admin/recorded-lectures",
    tags=["admin", "recorded-lectures"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[RecordedLectureOut])
async def list_recorded_lectures(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[RecordedLecture]:
    stmt = select(RecordedLecture).order_by(RecordedLecture.recorded_on.desc())
    return list((await db.execute(stmt)).scalars().all())


@router.post("", response_model=RecordedLectureOut, status_code=201)
async def create_recorded_lecture(
    body: RecordedLectureCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> RecordedLecture:
    if await db.get(Cohort, body.cohort_id) is None:
        raise HTTPException(status_code=400, detail="cohort not found")

    lecture = RecordedLecture(**body.model_dump())
    db.add(lecture)
    await db.commit()
    await db.refresh(lecture)
    return lecture


@router.patch("/{lecture_id}", response_model=RecordedLectureOut)
async def update_recorded_lecture(
    lecture_id: uuid.UUID,
    body: RecordedLectureUpdate,
    db: AsyncSession = Depends(get_db),
) -> RecordedLecture:
    lecture = await db.get(RecordedLecture, lecture_id)
    if lecture is None:
        raise HTTPException(status_code=404, detail="recorded lecture not found")
    updates = body.model_dump(exclude_unset=True)
    if "cohort_id" in updates:
        if updates["cohort_id"] is None:
            raise HTTPException(status_code=400, detail="cohort_id is required")
        if await db.get(Cohort, updates["cohort_id"]) is None:
            raise HTTPException(status_code=400, detail="cohort not found")
    for field, value in updates.items():
        setattr(lecture, field, value)
    await db.commit()
    await db.refresh(lecture)
    return lecture


@router.delete("/{lecture_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recorded_lecture(
    lecture_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    lecture = await db.get(RecordedLecture, lecture_id)
    if lecture is None:
        raise HTTPException(status_code=404, detail="recorded lecture not found")
    await db.delete(lecture)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
