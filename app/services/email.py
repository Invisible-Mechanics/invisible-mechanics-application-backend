"""Resend HTTP client. Used for transactional email (class reminders).

Supabase magic-link emails go through SMTP separately, configured in the
Supabase dashboard (Auth → SMTP) to point at Resend.
"""

import base64
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import Settings, get_settings

TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True)
class SendResult:
    id: str | None
    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class EmailAttachment:
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"


class EmailClient:
    """Abstract interface. Tests inject a FakeEmailClient that records sends."""

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str,
        attachments: list[EmailAttachment] | None = None,
    ) -> SendResult:  # pragma: no cover - interface
        raise NotImplementedError


class FakeEmailClient(EmailClient):
    """In-memory recorder for tests + dev when no Resend key is set."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str,
        attachments: list[EmailAttachment] | None = None,
    ) -> SendResult:
        self.sent.append(
            {
                "to": to,
                "subject": subject,
                "html": html,
                "text": text,
                "attachments": attachments or [],
            }
        )
        return SendResult(id=f"fake-{len(self.sent)}", ok=True)


class ResendEmailClient(EmailClient):
    def __init__(self, settings: Settings):
        self._settings = settings

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str,
        attachments: list[EmailAttachment] | None = None,
    ) -> SendResult:
        payload = {
            "from": self._settings.mail_from,
            "to": [to],
            "subject": subject,
            "html": html,
            "text": text,
        }
        if attachments:
            payload["attachments"] = [
                {
                    "filename": item.filename,
                    "content": base64.b64encode(item.content).decode("ascii"),
                    "content_type": item.content_type,
                }
                for item in attachments
            ]
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {self._settings.resend_api_key}"},
                json=payload,
            )
            if resp.status_code >= 400:
                return SendResult(id=None, ok=False, error=f"{resp.status_code} {resp.text}")
            data = resp.json()
            return SendResult(id=data.get("id"), ok=True)


def get_email_client() -> EmailClient:
    settings = get_settings()
    if settings.resend_api_key:
        return ResendEmailClient(settings)
    return FakeEmailClient()


def render_template(name: str, **context: object) -> str:
    """Load a template file and interpolate via str.format()."""
    path = TEMPLATES_DIR / name
    return path.read_text(encoding="utf-8").format(**context)
