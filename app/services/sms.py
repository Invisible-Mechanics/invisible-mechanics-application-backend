from dataclasses import dataclass, field

import httpx

from app.config import Settings, get_settings


@dataclass
class SMSResult:
    ok: bool
    error: str | None = None


class SMSClient:
    async def send_otp(self, *, phone: str, code: str) -> SMSResult:
        raise NotImplementedError


@dataclass
class FakeSMSClient(SMSClient):
    sent: list[dict[str, str]] = field(default_factory=list)

    async def send_otp(self, *, phone: str, code: str) -> SMSResult:
        self.sent.append({"phone": phone, "code": code})
        return SMSResult(ok=True)


class MSG91SMSClient(SMSClient):
    def __init__(self, settings: Settings):
        self._settings = settings

    async def send_otp(self, *, phone: str, code: str) -> SMSResult:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    "https://control.msg91.com/api/v5/otp",
                    params={
                        "template_id": self._settings.msg91_template_id,
                        "mobile": phone,
                        "authkey": self._settings.msg91_auth_key,
                        "otp": code,
                        "sender": self._settings.msg91_sender_id,
                        "otp_expiry": self._settings.msg91_otp_expiry_min,
                    },
                )
            if response.status_code >= 400:
                return SMSResult(ok=False, error=response.text[:500])
            data = response.json()
            if str(data.get("type", "")).lower() == "error":
                return SMSResult(ok=False, error=str(data.get("message", "MSG91 error")))
            return SMSResult(ok=True)
        except Exception as exc:
            return SMSResult(ok=False, error=str(exc))


def get_sms_client() -> SMSClient:
    settings = get_settings()
    if settings.msg91_auth_key:
        return MSG91SMSClient(settings)
    return FakeSMSClient()
