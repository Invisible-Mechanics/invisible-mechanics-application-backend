"""Thin async client for the Cloudflare REST API.

Wraps httpx against ``CLOUDFLARE_API_BASE_URL`` and binds the bearer token +
account id from settings so callers can't accidentally hardcode them.

Cloudflare wraps every successful response in ``{"result": ..., "success": true,
"errors": [...], "messages": [...]}``. ``.request()`` returns the parsed body
as-is and raises ``CloudflareApiError`` for any non-2xx or any 2xx with
``success: false`` so callers see the real failure mode.
"""

import base64
from typing import Any

import httpx

from app.config import Settings, get_settings


class CloudflareApiError(RuntimeError):
    def __init__(self, status: int, errors: list[dict[str, Any]] | None, body: Any):
        self.status = status
        self.errors = errors or []
        self.body = body
        msg = f"Cloudflare API {status}: {self.errors or body}"
        super().__init__(msg)


class CloudflareClient:
    """Account-scoped Cloudflare API client. One per process is fine."""

    def __init__(self, settings: Settings):
        if not settings.cloudflare_api_token:
            raise RuntimeError("CLOUDFLARE_API_TOKEN not configured")
        if not settings.cloudflare_account_id:
            raise RuntimeError("CLOUDFLARE_ACCOUNT_ID not configured")
        self._base_url = settings.cloudflare_api_base_url.rstrip("/")
        self._token = settings.cloudflare_api_token
        self.account_id = settings.cloudflare_account_id
        self.zone_id = settings.cloudflare_zone_id or None

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {self._token}"}
        async with httpx.AsyncClient(timeout=timeout) as http:
            resp = await http.request(method, url, headers=headers, json=json, params=params)
        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text}
        if resp.status_code >= 400 or (isinstance(body, dict) and body.get("success") is False):
            raise CloudflareApiError(
                resp.status_code,
                body.get("errors") if isinstance(body, dict) else None,
                body,
            )
        return body

    # ---- Convenience helpers (account-scoped) ----

    def account_path(self, *parts: str) -> str:
        return "/".join(["accounts", self.account_id, *parts])

    async def create_tus_upload(
        self,
        *,
        filename: str,
        size_bytes: int,
        require_signed_urls: bool = True,
        timeout: float = 15.0,
    ) -> tuple[str, str]:
        """Mint a one-time TUS upload URL for a Stream video.

        Cloudflare's TUS creation endpoint doesn't follow the standard
        ``{success,result}`` envelope: it returns 201 with the upload URL in
        the ``Location`` header and the assigned video UID in
        ``stream-media-id``. The browser then PATCHes to the returned URL
        with no auth (the URL itself is signed).

        Returns ``(video_uid, tus_upload_url)``.
        """
        name_b64 = base64.b64encode(filename.encode("utf-8")).decode("ascii")
        # Upload-Metadata is "key1 b64value1,key2 b64value2". An empty-string
        # value (which still needs a space) is how you set boolean flags like
        # `requiresignedurls`.
        meta_parts = [f"name {name_b64}"]
        if require_signed_urls:
            empty_b64 = base64.b64encode(b"").decode("ascii")
            meta_parts.append(f"requiresignedurls {empty_b64}")

        url = f"{self._base_url}/{self.account_path('stream')}?direct_user=true"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Tus-Resumable": "1.0.0",
            "Upload-Length": str(size_bytes),
            "Upload-Metadata": ",".join(meta_parts),
        }
        async with httpx.AsyncClient(timeout=timeout) as http:
            resp = await http.post(url, headers=headers)
        if resp.status_code != 201:
            try:
                body = resp.json()
            except ValueError:
                body = {"raw": resp.text}
            raise CloudflareApiError(
                resp.status_code,
                body.get("errors") if isinstance(body, dict) else None,
                body,
            )
        upload_url = resp.headers.get("Location") or resp.headers.get("location")
        uid = resp.headers.get("stream-media-id") or resp.headers.get("Stream-Media-Id")
        if not upload_url or not uid:
            raise CloudflareApiError(
                resp.status_code,
                None,
                "Cloudflare TUS create response missing Location / stream-media-id",
            )
        return uid, upload_url


def get_cloudflare_client() -> CloudflareClient:
    return CloudflareClient(get_settings())
