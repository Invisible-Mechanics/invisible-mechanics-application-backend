import asyncio

import httpx

from app.main import app
from app.services.email import SendResult, get_email_client


class SmokeEmailClient:
    async def send(self, *, to: str, subject: str, html: str, text: str) -> SendResult:
        return SendResult(id="smoke", ok=True)


async def main() -> None:
    app.dependency_overrides[get_email_client] = lambda: SmokeEmailClient()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/auth/request",
            json={"email": "codex-smoke@example.com", "next": "/account"},
        )
        print(response.status_code, response.text)
        response.raise_for_status()


if __name__ == "__main__":
    asyncio.run(main())
