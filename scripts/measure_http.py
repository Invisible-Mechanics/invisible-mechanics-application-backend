import asyncio
import time

import httpx


async def main() -> None:
    urls = [
        "http://127.0.0.1:8001/health",
        "http://127.0.0.1:8001/classes",
        "http://127.0.0.1:8001/cohorts",
        "http://127.0.0.1:8001/lectures",
        "http://127.0.0.1:3000/login",
        "http://127.0.0.1:3000/library",
        "http://127.0.0.1:3000/cohorts",
        "http://127.0.0.1:3000/schedule",
    ]
    async with httpx.AsyncClient(timeout=90) as client:
        for url in urls:
            start = time.perf_counter()
            try:
                response = await client.get(url)
                elapsed = (time.perf_counter() - start) * 1000
                print(
                    f"{url} {response.status_code} {elapsed:.0f}ms "
                    f"{len(response.content)} bytes offline={b'Backend is offline' in response.content}"
                )
            except Exception as exc:
                elapsed = (time.perf_counter() - start) * 1000
                print(f"{url} ERROR {elapsed:.0f}ms {exc}")


if __name__ == "__main__":
    asyncio.run(main())
