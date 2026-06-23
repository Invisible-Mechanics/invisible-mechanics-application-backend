import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Class, Cohort
from app.schemas import ClassOut, CohortOut

router = APIRouter(prefix="/cohorts", tags=["cohorts"])


@router.get("", response_model=list[CohortOut])
async def list_cohorts(db: AsyncSession = Depends(get_db)) -> list[Cohort]:
    stmt = select(Cohort).order_by(Cohort.start_date.asc().nullslast())
    return list((await db.execute(stmt)).scalars().all())


@router.get("/{cohort_id}", response_model=CohortOut)
async def get_cohort(cohort_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Cohort:
    cohort = await db.get(Cohort, cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="cohort not found")
    return cohort


@router.get("/{cohort_id}/classes", response_model=list[ClassOut])
async def list_cohort_classes(
    cohort_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[Class]:
    cohort = await db.get(Cohort, cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="cohort not found")
    stmt = (
        select(Class)
        .where(Class.cohort_id == cohort_id)
        .order_by(Class.scheduled_start.asc())
    )
    return list((await db.execute(stmt)).scalars().all())
