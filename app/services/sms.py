from dataclasses import dataclass, field
import logging

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)


@dataclass
class SMSResult:
    ok: bool
    error: str | None = None
    response_body: object | None = None


class SMSClient:
    async def send_otp(self, *, phone: str, code: str) -> SMSResult:
        raise NotImplementedError

    async def send_enrollment(
        self,
        *,
        phone: str,
        program_title: str,
        program_details: str,
    ) -> SMSResult:
        raise NotImplementedError


@dataclass
class FakeSMSClient(SMSClient):
    sent: list[dict[str, str]] = field(default_factory=list)

    async def send_otp(self, *, phone: str, code: str) -> SMSResult:
        self.sent.append({"phone": phone, "code": code})
        return SMSResult(ok=True)

    async def send_enrollment(
        self,
        *,
        phone: str,
        program_title: str,
        program_details: str,
    ) -> SMSResult:
        self.sent.append(
            {
                "phone": phone,
                "program_title": program_title,
                "program_details": program_details,
            }
        )
        return SMSResult(ok=True)


class MSG91SMSClient(SMSClient):
    def __init__(self, settings: Settings):
        self._settings = settings

    async def send_otp(self, *, phone: str, code: str) -> SMSResult:
        return await self._send_flow(
            phone=phone,
            template_id=self._settings.msg91_template_id,
            purpose="otp",
            variables={"var1": code},
        )

    async def send_enrollment(
        self,
        *,
        phone: str,
        program_title: str,
        program_details: str,
    ) -> SMSResult:
        return await self._send_flow(
            phone=phone,
            template_id=self._settings.msg91_enrollment_template_id,
            purpose="enrollment",
            variables={
                "var1": program_title,
                "var2": program_details,
                "var3": program_details,
            },
        )

    async def _send_flow(
        self,
        *,
        phone: str,
        template_id: str,
        purpose: str,
        variables: dict[str, str],
    ) -> SMSResult:
        missing = [
            key
            for key, value in {
                "MSG91_AUTH_KEY": self._settings.msg91_auth_key,
                "MSG91_TEMPLATE_ID": template_id,
                "MSG91_SENDER_ID": self._settings.msg91_sender_id,
            }.items()
            if not value
        ]
        if missing:
            message = f"missing required MSG91 env vars: {', '.join(missing)}"
            logger.error("msg91 %s config error: %s", purpose, message)
            return SMSResult(ok=False, error=message, response_body={"message": message})

        response_body: object
        try:
            recipient = {"mobiles": phone, **variables}
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    "https://control.msg91.com/api/v5/flow/",
                    headers={
                        "Content-Type": "application/json",
                        "authkey": self._settings.msg91_auth_key,
                    },
                    json={
                        "template_id": template_id,
                        "sender": self._settings.msg91_sender_id,
                        "short_url": "0",
                        "recipients": [recipient],
                    },
                )
            try:
                response_body = response.json()
            except ValueError:
                response_body = {"raw": response.text}

            logger.info("MSG91 %s RESPONSE STATUS %s", purpose.upper(), response.status_code)
            logger.info(
                "MSG91 %s RESPONSE BODY phone_tail=%s template_id=%s body=%s",
                purpose.upper(),
                phone[-4:],
                template_id,
                response_body,
            )

            if response.status_code >= 400:
                return SMSResult(
                    ok=False,
                    error=f"MSG91 HTTP {response.status_code}",
                    response_body=response_body,
                )
            if not isinstance(response_body, dict):
                return SMSResult(ok=True, response_body=response_body)

            data = response_body
            msg91_type = str(data.get("type", "")).lower()
            msg91_message = str(data.get("message", data.get("error", "")))
            if msg91_type == "error":
                return SMSResult(
                    ok=False,
                    error=msg91_message or "MSG91 error",
                    response_body=response_body,
                )
            return SMSResult(ok=True, response_body=response_body)
        except Exception as exc:
            logger.exception(
                "MSG91 %s API error phone_tail=%s template_id=%s",
                purpose.upper(),
                phone[-4:],
                template_id,
            )
            return SMSResult(
                ok=False,
                error=str(exc),
                response_body={"message": str(exc)},
            )


def get_sms_client() -> SMSClient:
    settings = get_settings()
    return MSG91SMSClient(settings)
