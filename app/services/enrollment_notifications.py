"""Enrollment confirmation notifications sent after successful joins."""

import logging
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Cohort, Payment, User
from app.services.sms import get_sms_client

logger = logging.getLogger(__name__)


def _student_name(user: User) -> str:
    return user.name or user.email.split("@", 1)[0] or "Student"


def _format_date(value: date | None) -> str | None:
    return value.strftime("%d %b %Y") if value else None


def _cohort_details(cohort: Cohort) -> str:
    parts: list[str] = []
    if cohort.start_date:
        parts.append(f"Starts {_format_date(cohort.start_date)}")
    if cohort.end_date:
        parts.append(f"Ends {_format_date(cohort.end_date)}")
    if cohort.target_exam:
        parts.append(cohort.target_exam.upper())
    if cohort.target_year:
        parts.append(str(cohort.target_year))
    return " | ".join(parts) if parts else "Enrollment confirmed"


async def send_masterclass_enrollment_notification_best_effort(user: User) -> None:
    if not user.phone:
        logger.info("masterclass enrollment notification skipped user_id=%s reason=no_phone", user.id)
        return
    try:
        settings = get_settings()
        result = await get_sms_client().send_enrollment(
            phone=user.phone,
            student_name=_student_name(user),
            program_title="Invisible Mechanics Live Masterclass",
            program_details=settings.masterclass_live_at_text,
        )
        if not result.ok:
            logger.warning(
                "masterclass enrollment notification failed user_id=%s error=%s",
                user.id,
                result.error,
            )
    except Exception:  # noqa: BLE001
        logger.exception("masterclass enrollment notification crashed user_id=%s", user.id)


async def send_cohort_enrollment_notification_best_effort(
    db: AsyncSession,
    payment: Payment,
) -> None:
    if payment.scope_type != "cohort":
        return
    try:
        user = await db.get(User, payment.user_id)
        cohort = await db.get(Cohort, payment.scope_id)
        if user is None or cohort is None:
            return
        if not user.phone:
            logger.info("cohort enrollment notification skipped user_id=%s reason=no_phone", user.id)
            return
        result = await get_sms_client().send_enrollment(
            phone=user.phone,
            student_name=_student_name(user),
            program_title=cohort.title,
            program_details=_cohort_details(cohort),
        )
        if not result.ok:
            logger.warning(
                "cohort enrollment notification failed payment_id=%s user_id=%s error=%s",
                payment.id,
                user.id,
                result.error,
            )
    except Exception:  # noqa: BLE001
        logger.exception("cohort enrollment notification crashed payment_id=%s", payment.id)
