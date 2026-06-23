"""Cloudflare Stream Live: manage live inputs and look up their recordings.

A live input is the persistent endpoint an instructor pushes RTMPS/SRT into.
We create one per scheduled class on admin create_class, and delete it on
class delete. Cloudflare automatically saves each broadcast as a Stream video
(when ``recording.mode = "automatic"``), which the class-recording flow
attaches to the class once the broadcast ends.

FakeStreamLiveClient (no Cloudflare API token) returns deterministic
placeholder data so the full admin -> join -> recording flow stays testable.
"""

import secrets
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.config import Settings, cloudflare_is_configured, get_settings
from app.services.cloudflare_api import CloudflareClient


@dataclass(frozen=True)
class LiveInput:
    """What the admin/instructor needs to start broadcasting."""

    uid: str
    rtmps_url: str
    rtmps_stream_key: str


@dataclass(frozen=True)
class LiveInputStatus:
    """State of a live input + any recordings already produced."""

    uid: str
    connected: bool
    recording_video_uids: list[str]


class StreamLiveClient(ABC):
    @abstractmethod
    async def create_live_input(self, *, name: str) -> LiveInput: ...

    @abstractmethod
    async def get_keys(self, uid: str) -> LiveInput: ...

    @abstractmethod
    async def delete_live_input(self, uid: str) -> None: ...

    @abstractmethod
    async def get_status(self, uid: str) -> LiveInputStatus: ...


class FakeStreamLiveClient(StreamLiveClient):
    """In-process fake. Storage is class-level so create/get round-trip across
    the per-request instances FastAPI's dependency injection produces."""

    _keys: dict[str, LiveInput] = {}

    async def create_live_input(self, *, name: str) -> LiveInput:  # noqa: ARG002
        uid = uuid.uuid4().hex[:32]
        key = secrets.token_urlsafe(24)
        li = LiveInput(
            uid=uid,
            rtmps_url="rtmps://live.cloudflare.com:443/live/",
            rtmps_stream_key=key,
        )
        self._keys[uid] = li
        return li

    async def get_keys(self, uid: str) -> LiveInput:
        if uid not in self._keys:
            # Re-materialize a deterministic-ish key so flows that bypassed
            # create_live_input (e.g. fixture-seeded classes) still work.
            self._keys[uid] = LiveInput(
                uid=uid,
                rtmps_url="rtmps://live.cloudflare.com:443/live/",
                rtmps_stream_key=f"fake-key-{uid[:8]}",
            )
        return self._keys[uid]

    async def delete_live_input(self, uid: str) -> None:
        self._keys.pop(uid, None)

    async def get_status(self, uid: str) -> LiveInputStatus:
        # A fake recording UID lets the "attach recording" flow stay exercised
        # in tests without a real Cloudflare account.
        return LiveInputStatus(
            uid=uid,
            connected=False,
            recording_video_uids=[f"rec-{uid[:12]}"],
        )


class LiveStreamLiveClient(StreamLiveClient):
    def __init__(self, settings: Settings):
        self._cf = CloudflareClient(settings)
        self._retention_days = settings.stream_recording_retention_days
        self._require_signed = bool(settings.cloudflare_stream_signing_key_id)

    async def create_live_input(self, *, name: str) -> LiveInput:
        body = await self._cf.request(
            "POST",
            self._cf.account_path("stream", "live_inputs"),
            json={
                "meta": {"name": name},
                "recording": {
                    "mode": "automatic",
                    "requireSignedURLs": self._require_signed,
                    "timeoutSeconds": 10,
                },
                "deleteRecordingAfterDays": self._retention_days,
            },
        )
        result = body["result"]
        rtmps = result.get("rtmps") or {}
        return LiveInput(
            uid=result["uid"],
            rtmps_url=rtmps.get("url", ""),
            rtmps_stream_key=rtmps.get("streamKey", ""),
        )

    async def get_keys(self, uid: str) -> LiveInput:
        body = await self._cf.request(
            "GET",
            self._cf.account_path("stream", "live_inputs", uid),
        )
        result = body["result"]
        rtmps = result.get("rtmps") or {}
        return LiveInput(
            uid=result["uid"],
            rtmps_url=rtmps.get("url", ""),
            rtmps_stream_key=rtmps.get("streamKey", ""),
        )

    async def delete_live_input(self, uid: str) -> None:
        await self._cf.request(
            "DELETE",
            self._cf.account_path("stream", "live_inputs", uid),
        )

    async def get_status(self, uid: str) -> LiveInputStatus:
        # Two calls: the input itself for connection state, and its videos
        # for the list of recordings.
        details = await self._cf.request(
            "GET",
            self._cf.account_path("stream", "live_inputs", uid),
        )
        status = ((details.get("result") or {}).get("status")) or {}
        connected = str(status.get("current", {}).get("state", "")) == "connected"

        videos = await self._cf.request(
            "GET",
            self._cf.account_path("stream", "live_inputs", uid, "videos"),
        )
        video_uids = [v["uid"] for v in (videos.get("result") or []) if v.get("uid")]
        return LiveInputStatus(uid=uid, connected=connected, recording_video_uids=video_uids)


def get_stream_live_client() -> StreamLiveClient:
    settings = get_settings()
    if cloudflare_is_configured(settings):
        return LiveStreamLiveClient(settings)
    return FakeStreamLiveClient()
