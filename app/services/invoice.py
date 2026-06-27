"""Invoice PDF generation and receipt email delivery."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Class, Cohort, Payment, RecordedLecture, User
from app.services.email import EmailAttachment, get_email_client

logger = logging.getLogger(__name__)


BUSINESS = {
    "legal_name": "Invisible Mechanics Pvt. Ltd.",
    "brand": "Invisible Mechanics",
    "gstin": "29AAHCI7871H1Z0",
    "cin": "U85491KA2024PTC191508",
    "address": (
        "Fourth Floor, Site.54, Yelenahalli Main road, Akshayanagar, "
        "Bangur Hobli, Road, off Bannergatta Road, Bengaluru, Karnataka 560114"
    ),
    "email": "support@invisiblemechanics.com",
    "phone": "+91 6290683639",
}


@dataclass(frozen=True)
class InvoiceItem:
    title: str
    kind: str


def _money(paise: int) -> str:
    amount = (Decimal(paise) / Decimal(100)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return f"INR {amount}"


def _escape_pdf_text(value: object) -> str:
    text = str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return text.encode("latin-1", "replace").decode("latin-1")


def _pdf_lines_to_bytes(lines: list[str]) -> bytes:
    stream_parts = ["BT", "/F1 11 Tf", "50 790 Td", "14 TL"]
    first = True
    for line in lines:
        if not first:
            stream_parts.append("T*")
        stream_parts.append(f"({_escape_pdf_text(line)}) Tj")
        first = False
    stream_parts.append("ET")
    stream = "\n".join(stream_parts).encode("latin-1")

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_at = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n".encode("ascii")
    )
    return bytes(pdf)


async def _invoice_item(db: AsyncSession, payment: Payment) -> InvoiceItem:
    if payment.scope_type == "cohort":
        cohort = await db.get(Cohort, payment.scope_id)
        return InvoiceItem(title=cohort.title if cohort else str(payment.scope_id), kind="Cohort")
    if payment.scope_type == "class":
        klass = await db.get(Class, payment.scope_id)
        return InvoiceItem(title=klass.title if klass else str(payment.scope_id), kind="Live class")
    if payment.scope_type == "recorded_lecture":
        lecture = await db.get(RecordedLecture, payment.scope_id)
        return InvoiceItem(
            title=lecture.title if lecture else str(payment.scope_id),
            kind="Recorded lecture",
        )
    return InvoiceItem(title=str(payment.scope_id), kind=payment.scope_type)


async def build_invoice_pdf(db: AsyncSession, payment: Payment, user: User) -> bytes:
    item = await _invoice_item(db, payment)
    issued_at = datetime.now(UTC).strftime("%d %b %Y, %H:%M UTC")
    invoice_no = f"IM-{str(payment.id)[:8].upper()}"
    lines = [
        "TAX INVOICE / PAYMENT RECEIPT",
        "",
        BUSINESS["legal_name"],
        f"Brand: {BUSINESS['brand']}",
        f"GSTIN: {BUSINESS['gstin']}",
        f"CIN: {BUSINESS['cin']}",
        f"Address: {BUSINESS['address']}",
        f"Support: {BUSINESS['email']} | {BUSINESS['phone']}",
        "",
        f"Invoice No: {invoice_no}",
        f"Issued At: {issued_at}",
        "",
        "Billed To",
        f"Name: {user.name or '-'}",
        f"Email: {user.email}",
        f"Mobile: {user.phone or '-'}",
        f"User ID: {user.id}",
        "",
        "Purchase Details",
        f"Item Type: {item.kind}",
        f"Item: {item.title}",
        f"Amount Paid: {_money(payment.amount)}",
        f"Currency: {payment.currency}",
        f"Payment Status: {payment.status}",
        f"Razorpay Order ID: {payment.razorpay_order_id}",
        f"Razorpay Payment ID: {payment.razorpay_payment_id or '-'}",
        "",
        "This is a computer-generated invoice/receipt for an online education service.",
    ]
    return _pdf_lines_to_bytes(lines)


async def send_invoice_email_best_effort(db: AsyncSession, payment: Payment) -> None:
    try:
        user = await db.get(User, payment.user_id)
        if user is None:
            return
        item = await _invoice_item(db, payment)
        pdf = await build_invoice_pdf(db, payment, user)
        invoice_no = f"IM-{str(payment.id)[:8].upper()}"
        email = get_email_client()
        result = await email.send(
            to=user.email,
            subject=f"Invoice {invoice_no} - {BUSINESS['brand']}",
            html=(
                f"<p>Hi {user.name or 'Student'},</p>"
                f"<p>Payment received for <strong>{item.title}</strong>.</p>"
                "<p>Your invoice is attached as a PDF.</p>"
                f"<p>Regards,<br>{BUSINESS['brand']}</p>"
            ),
            text=(
                f"Hi {user.name or 'Student'},\n\n"
                f"Payment received for {item.title}.\n"
                "Your invoice is attached as a PDF.\n\n"
                f"Regards,\n{BUSINESS['brand']}"
            ),
            attachments=[
                EmailAttachment(
                    filename=f"{invoice_no}.pdf",
                    content=pdf,
                    content_type="application/pdf",
                )
            ],
        )
        if not result.ok:
            logger.warning("invoice email failed payment_id=%s error=%s", payment.id, result.error)
    except Exception:  # noqa: BLE001
        logger.exception("invoice email generation failed payment_id=%s", payment.id)
