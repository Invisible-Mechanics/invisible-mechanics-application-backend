import asyncio
import time

import httpx

from app.main import app


async def request(client: httpx.AsyncClient, path: str) -> None:
    start = time.perf_counter()
    response = await client.get(path)
    elapsed = time.perf_counter() - start
    body = response.text[:300].replace("\n", " ")
    print(f"{path} -> {response.status_code} in {elapsed:.2f}s {body}")
    response.raise_for_status()


async def main() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=30) as client:
        for path in ["/health", "/classes", "/cohorts", "/lectures"]:
            await request(client, path)


if __name__ == "__main__":
    asyncio.run(main())
