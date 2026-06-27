"""Enrollment confirmation notifications sent after successful joins."""

import logging
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Cohort, Payment, User
from app.services.email import get_email_client
from app.services.sms import get_sms_client

logger = logging.getLogger(__name__)


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


async def _send_enrollment_email_best_effort(
    *,
    user: User,
    program_title: str,
    program_details: str,
) -> None:
    try:
        email = get_email_client()
        result = await email.send(
            to=user.email,
            subject=f"Enrollment confirmed - {program_title}",
            html=(
                "<p>Hi,</p>"
                f"<p>Your enrollment for <strong>{program_title}</strong> is confirmed.</p>"
                f"<p>{program_details}</p>"
                "<p>Regards,<br>Invisible Mechanics</p>"
            ),
            text=(
                "Hi,\n\n"
                f"Your enrollment for {program_title} is confirmed.\n"
                f"{program_details}\n\n"
                "Regards,\nInvisible Mechanics"
            ),
        )
        if not result.ok:
            logger.warning(
                "enrollment email failed user_id=%s program=%s error=%s",
                user.id,
                program_title,
                result.error,
            )
    except Exception:  # noqa: BLE001
        logger.exception("enrollment email crashed user_id=%s", user.id)


async def _send_enrollment_sms_best_effort(
    *,
    user: User,
    program_title: str,
    program_details: str,
) -> None:
    if not user.phone:
        logger.info("enrollment sms skipped user_id=%s reason=no_phone", user.id)
        return
    try:
        result = await get_sms_client().send_enrollment(
            phone=user.phone,
            program_title=program_title,
            program_details=program_details,
        )
        if not result.ok:
            logger.warning(
                "enrollment sms failed user_id=%s program=%s error=%s",
                user.id,
                program_title,
                result.error,
            )
    except Exception:  # noqa: BLE001
        logger.exception("enrollment sms crashed user_id=%s", user.id)


async def send_masterclass_enrollment_notification_best_effort(user: User) -> None:
    settings = get_settings()
    program_title = settings.masterclass_topic_title
    program_details = settings.masterclass_live_at_text
    await _send_enrollment_email_best_effort(
        user=user,
        program_title=program_title,
        program_details=program_details,
    )
    await _send_enrollment_sms_best_effort(
        user=user,
        program_title=program_title,
        program_details=program_details,
    )


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
        program_details = _cohort_details(cohort)
        await _send_enrollment_email_best_effort(
            user=user,
            program_title=cohort.title,
            program_details=program_details,
        )
        await _send_enrollment_sms_best_effort(
            user=user,
            program_title=cohort.title,
            program_details=program_details,
        )
    except Exception:  # noqa: BLE001
        logger.exception("cohort enrollment notification crashed payment_id=%s", payment.id)
