# Matrix driver via matrix-nio (async).
#
# Receive: AsyncClient.sync_forever() long-poll loop.  RoomMessageText,
#          RoomMessageImage, RoomMessageVideo, RoomMessageAudio and
#          RoomMessageFile events are forwarded to the bridge.  Media is
#          downloaded eagerly via the authenticated client so downstream
#          drivers never need Matrix credentials.
# Send:    room_send() for text; upload() + room_send() for media.
#
# Config keys (under matrix.<instance_id>):
#   homeserver    – Homeserver URL, e.g. "https://matrix.org" (required)
#   user_id       – Full Matrix user ID, e.g. "@bot:matrix.org" (required)
#   password      – Login password (required unless access_token is set)
#   access_token  – Access token (alternative to password)
#   max_file_size – Max bytes per attachment (default 50 MB)
#
# Rule channel keys:
#   room_id – Matrix room ID, e.g. "!abc123:matrix.org"

import io

from nio import (
    AsyncClient,
    DownloadResponse,
    LoginResponse,
    MatrixRoom,
    ProfileGetAvatarResponse,
    RoomMessageAudio,
    RoomMessageFile,
    RoomMessageImage,
    RoomMessageText,
    RoomMessageVideo,
    UploadResponse,
)

import services.logger as log
import services.media as media
from services.message import Attachment, NormalizedMessage
from drivers import BaseDriver

l = log.get_logger()

_DEFAULT_MAX = 50 * 1024 * 1024  # 50 MB

_MSGTYPES = {
    "image": "m.image",
    "video": "m.video",
    "voice": "m.audio",
    "file":  "m.file",
}


class MatrixDriver(BaseDriver):

    def __init__(self, instance_id: str, config: dict, bridge):
        super().__init__(instance_id, config, bridge)
        self._client: AsyncClient | None = None
        self._user_id: str = ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self.bridge.register_sender(self.instance_id, self.send)

        homeserver    = self.config.get("homeserver", "")
        user_id       = self.config.get("user_id", "")
        password      = self.config.get("password", "")
        access_token  = self.config.get("access_token", "")

        if not homeserver or not user_id:
            l.error(f"Matrix [{self.instance_id}] homeserver and user_id are required")
            return

        if not password and not access_token:
            l.error(f"Matrix [{self.instance_id}] either password or access_token is required")
            return

        self._user_id = user_id
        self._client = AsyncClient(homeserver, user_id)

        if access_token:
            self._client.access_token = access_token
            self._client.user_id = user_id
        else:
            resp = await self._client.login(password)
            if not isinstance(resp, LoginResponse):
                l.error(f"Matrix [{self.instance_id}] login failed: {resp}")
                await self._client.close()
                self._client = None
                return

        self._client.add_event_callback(self._on_text,  RoomMessageText)
        self._client.add_event_callback(self._on_media, RoomMessageImage)
        self._client.add_event_callback(self._on_media, RoomMessageVideo)
        self._client.add_event_callback(self._on_media, RoomMessageAudio)
        self._client.add_event_callback(self._on_media, RoomMessageFile)

        l.info(f"Matrix [{self.instance_id}] connected, starting sync")
        # Initial sync to mark already-present messages as seen
        await self._client.sync(timeout=0, full_state=True)
        await self._client.sync_forever(timeout=30000, loop_sleep_time=1000)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _mxc_to_http(self, mxc_uri: str) -> str:
        """Convert an mxc:// URI to an HTTP download URL."""
        if not mxc_uri or not mxc_uri.startswith("mxc://"):
            return ""
        homeserver = self.config.get("homeserver", "").rstrip("/")
        return f"{homeserver}/_matrix/media/v3/download/{mxc_uri[6:]}"

    def _display_name(self, room: MatrixRoom, user_id: str) -> str:
        member = room.users.get(user_id)
        if member and member.display_name:
            return member.display_name
        # Fall back to the local part of the MXID (@user:server → user)
        return user_id.split(":")[0].lstrip("@") if ":" in user_id else user_id

    async def _get_avatar(self, user_id: str) -> str:
        if self._client is None:
            return ""
        try:
            resp = await self._client.get_avatar(user_id)
            if isinstance(resp, ProfileGetAvatarResponse) and resp.avatar_url:
                return self._mxc_to_http(resp.avatar_url)
        except Exception:
            pass
        return ""

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def _on_text(self, room: MatrixRoom, event: RoomMessageText):
        if event.sender == self._user_id:
            return
        if event.msgtype != "m.text":
            return
        text = event.body or ""
        if not text.strip():
            return

        normalized = NormalizedMessage(
            platform="matrix",
            instance_id=self.instance_id,
            channel={"room_id": room.room_id},
            user=self._display_name(room, event.sender),
            user_id=event.sender,
            user_avatar=await self._get_avatar(event.sender),
            text=text,
        )
        await self.bridge.on_message(normalized)

    async def _on_media(self, room: MatrixRoom, event):
        if event.sender == self._user_id:
            return

        if isinstance(event, RoomMessageImage):
            att_type = "image"
        elif isinstance(event, RoomMessageVideo):
            att_type = "video"
        elif isinstance(event, RoomMessageAudio):
            att_type = "voice"
        else:
            att_type = "file"

        max_size: int = self.config.get("max_file_size", _DEFAULT_MAX)

        # Skip early if the declared size already exceeds the limit
        info = getattr(event, "info", None)
        declared_size = getattr(info, "size", None) if info else None
        if declared_size and declared_size > max_size:
            l.debug(
                f"Matrix [{self.instance_id}] skipping {event.body!r}: "
                f"{declared_size} > {max_size}"
            )
            return

        # Eagerly download via the authenticated client
        mxc = getattr(event, "url", "") or ""
        att_data: bytes | None = None
        att_url = ""
        if mxc and self._client:
            try:
                dl = await self._client.download(mxc_uri=mxc)
                if isinstance(dl, DownloadResponse):
                    if len(dl.body) <= max_size:
                        att_data = dl.body
                    else:
                        l.debug(
                            f"Matrix [{self.instance_id}] {event.body!r} "
                            "exceeds size limit after download"
                        )
                        return
                else:
                    l.warning(f"Matrix [{self.instance_id}] media download error: {dl}")
                    att_url = self._mxc_to_http(mxc)
            except Exception as e:
                l.warning(f"Matrix [{self.instance_id}] media download failed: {e}")
                att_url = self._mxc_to_http(mxc)

        normalized = NormalizedMessage(
            platform="matrix",
            instance_id=self.instance_id,
            channel={"room_id": room.room_id},
            user=self._display_name(room, event.sender),
            user_id=event.sender,
            user_avatar=await self._get_avatar(event.sender),
            text="",
            attachments=[Attachment(
                type=att_type,
                url=att_url,
                name=event.body or "",
                data=att_data,
            )],
        )
        await self.bridge.on_message(normalized)

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def send(
        self,
        channel: dict,
        text: str,
        attachments: list[Attachment] | None = None,
        **kwargs,
    ):
        if self._client is None:
            l.warning(f"Matrix [{self.instance_id}] send: driver not started")
            return

        room_id = channel.get("room_id")
        if not room_id:
            l.warning(f"Matrix [{self.instance_id}] send: no room_id in channel {channel}")
            return

        rich_header = kwargs.get("rich_header")
        if rich_header:
            t = rich_header.get("title", "")
            c = rich_header.get("content", "")
            prefix = f"**{t}**" + (f" · *{c}*" if c else "")
            text = f"{prefix}\n{text}" if text else prefix

        max_size: int = self.config.get("max_file_size", _DEFAULT_MAX)

        if text.strip():
            try:
                await self._client.room_send(
                    room_id,
                    "m.room.message",
                    {"msgtype": "m.text", "body": text},
                    ignore_unverified_devices=True,
                )
            except Exception as e:
                l.error(f"Matrix [{self.instance_id}] send text failed: {e}")

        for att in (attachments or []):
            if not att.url and att.data is None:
                continue

            result = await media.fetch_attachment(att, max_size)
            if not result:
                label = att.name or att.url or ""
                await self._send_text_fallback(room_id, f"[{att.type.capitalize()}: {label}]")
                continue

            data_bytes, mime = result
            fname = media.filename_for(att.name, mime)

            try:
                upload_resp, _ = await self._client.upload(
                    io.BytesIO(data_bytes),
                    content_type=mime,
                    filename=fname,
                    filesize=len(data_bytes),
                )
                if not isinstance(upload_resp, UploadResponse):
                    raise RuntimeError(f"Upload response: {upload_resp}")
                mxc_uri = upload_resp.content_uri
            except Exception as e:
                l.error(f"Matrix [{self.instance_id}] media upload failed: {e}")
                label = att.name or att.url or fname
                await self._send_text_fallback(room_id, f"[{att.type.capitalize()}: {label}]")
                continue

            content = {
                "msgtype": _MSGTYPES.get(att.type, "m.file"),
                "url": mxc_uri,
                "body": fname,
                "info": {"mimetype": mime, "size": len(data_bytes)},
            }
            try:
                await self._client.room_send(
                    room_id,
                    "m.room.message",
                    content,
                    ignore_unverified_devices=True,
                )
            except Exception as e:
                l.error(f"Matrix [{self.instance_id}] send media failed: {e}")

    async def _send_text_fallback(self, room_id: str, body: str) -> None:
        if self._client is None:
            return
        try:
            await self._client.room_send(
                room_id,
                "m.room.message",
                {"msgtype": "m.text", "body": body},
                ignore_unverified_devices=True,
            )
        except Exception as e:
            l.error(f"Matrix [{self.instance_id}] fallback send failed: {e}")
