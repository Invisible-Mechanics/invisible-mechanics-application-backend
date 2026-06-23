"""Cloudflare Stream signed-playback client.

For gated playback, Cloudflare Stream requires a short-lived JWT (RS256) that
encodes the video UID + expiry, signed with a Stream Signing Key created via
the Cloudflare API. The player then uses:

  https://customer-<code>.cloudflarestream.com/<jwt>/manifest/video.m3u8
  https://customer-<code>.cloudflarestream.com/<jwt>/iframe

Token minting is a local crypto operation (no network call), so this stays
sync inside async endpoints.

FakeStreamClient (no creds) returns deterministic placeholder URLs so the
end-to-end playback flow is fully testable without real Cloudflare creds.
Swap in real creds via env to use LiveStreamClient.
"""

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta

from app.config import Settings, get_settings


class StreamClient(ABC):
    @abstractmethod
    def sign_playback(self, *, video_uid: str, ttl_sec: int) -> "StreamPlayback": ...


class StreamPlayback:
    """Everything the player needs to render a single video."""

    def __init__(self, *, token: str, hls_url: str, dash_url: str, iframe_url: str, expires_at: datetime):
        self.token = token
        self.hls_url = hls_url
        self.dash_url = dash_url
        self.iframe_url = iframe_url
        self.expires_at = expires_at


class FakeStreamClient(StreamClient):
    def sign_playback(self, *, video_uid: str, ttl_sec: int) -> StreamPlayback:
        token = f"fake-token-{video_uid}-{ttl_sec}"
        base = f"https://fake-stream.local/{token}"
        return StreamPlayback(
            token=token,
            hls_url=f"{base}/manifest/video.m3u8",
            dash_url=f"{base}/manifest/video.mpd",
            iframe_url=f"{base}/iframe",
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_sec),
        )


class LiveStreamClient(StreamClient):
    def __init__(self, settings: Settings):
        if not settings.cloudflare_stream_customer_code:
            raise RuntimeError("CLOUDFLARE_STREAM_CUSTOMER_CODE not set")
        if not settings.cloudflare_stream_signing_key_id:
            raise RuntimeError("CLOUDFLARE_STREAM_SIGNING_KEY_ID not set")
        if not settings.cloudflare_stream_signing_key_pem:
            raise RuntimeError("CLOUDFLARE_STREAM_SIGNING_KEY_PEM not set")

        self._customer_code = settings.cloudflare_stream_customer_code
        self._key_id = settings.cloudflare_stream_signing_key_id
        # The PEM may arrive with literal "\n" sequences when copied from an env
        # secret manager — normalize so PyJWT can parse it.
        self._pem = settings.cloudflare_stream_signing_key_pem.replace("\\n", "\n").encode("utf-8")

    def sign_playback(self, *, video_uid: str, ttl_sec: int) -> StreamPlayback:
        import jwt  # imported here to keep the cold path light

        now = datetime.now(UTC)
        exp = now + timedelta(seconds=ttl_sec)
        claims = {
            "kid": self._key_id,
            "sub": video_uid,
            "exp": int(exp.timestamp()),
            "nbf": int(now.timestamp()),
        }
        token = jwt.encode(
            claims,
            self._pem,
            algorithm="RS256",
            headers={"kid": self._key_id},
        )
        base = f"https://customer-{self._customer_code}.cloudflarestream.com/{token}"
        return StreamPlayback(
            token=token,
            hls_url=f"{base}/manifest/video.m3u8",
            dash_url=f"{base}/manifest/video.mpd",
            iframe_url=f"{base}/iframe",
            expires_at=exp,
        )


def get_stream_client() -> StreamClient:
    settings = get_settings()
    if (
        settings.cloudflare_stream_customer_code
        and settings.cloudflare_stream_signing_key_id
        and settings.cloudflare_stream_signing_key_pem
    ):
        return LiveStreamClient(settings)
    return FakeStreamClient()
