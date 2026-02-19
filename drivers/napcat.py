# QQ driver via NapCat (OneBot 11 WebSocket protocol).
# NapCat acts as a WebSocket server; this driver connects as a client,
# receives push events, and sends actions over the same connection.
#
# Config keys (under napcat.<instance_id>):
#   ws_url        – WebSocket URL, e.g. "ws://127.0.0.1:3001"
#   ws_token      – Optional access token
#   max_file_size – Max bytes to download when bridging media (default 10 MB)

import asyncio
import base64
import json
import uuid
from pathlib import Path

import websockets
import websockets.exceptions

import services.logger as log
import services.media as media
from services.message import Attachment, NormalizedMessage
from drivers import BaseDriver

l = log.get_logger()

_DEFAULT_MAX = 10 * 1024 * 1024  # 10 MB

# ---------------------------------------------------------------------------
# CQ face GIF database
# ---------------------------------------------------------------------------

# Resolved once at import time so path traversal checks are always anchored to
# the same absolute directory, even if the working directory changes.
_FACE_DB: Path = (Path(__file__).parent.parent / "db" / "cqface-gif").resolve()


def _load_face_gif(face_id_raw) -> bytes | None:
    """
    Safely load a QQ face GIF from the local database.

    Security:
    - Layer 1: The face ID is parsed as a non-negative integer.  Integers
      cannot contain path separators or ``..``, so no traversal is possible
      by construction.
    - Layer 2: The resolved candidate path is checked with
      ``Path.is_relative_to(_FACE_DB)`` as a hard guarantee — this catches
      any edge cases such as OS-level symlinks that point outside the db dir.

    Returns ``None`` if the ID is invalid, escapes the database directory,
    or the file simply does not exist.
    """
    try:
        face_id = int(face_id_raw)
        if face_id < 0:
            raise ValueError("negative id")
    except (TypeError, ValueError):
        l.warning(f"Invalid face ID {face_id_raw!r} — ignored")
        return None

    candidate = (_FACE_DB / f"{face_id}.gif").resolve()

    # Layer 2 path-traversal guard.
    if not candidate.is_relative_to(_FACE_DB):
        l.warning(f"Face path {candidate} escapes database dir — blocked")
        return None

    if not candidate.is_file():
        return None

    try:
        return candidate.read_bytes()
    except OSError as e:
        l.error(f"Failed to read face GIF {candidate}: {e}")
        return None


class NapCatDriver(BaseDriver):

    def __init__(self, instance_id: str, config: dict, bridge):
        super().__init__(instance_id, config, bridge)
        self._ws: websockets.WebSocketClientProtocol | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self.bridge.register_sender(self.instance_id, self.send)

        ws_url = self.config.get("ws_url", "ws://127.0.0.1:3001")
        token = self.config.get("ws_token")
        if token:
            sep = "&" if "?" in ws_url else "?"
            ws_url = f"{ws_url}{sep}access_token={token}"

        l.info(f"NapCat [{self.instance_id}] connecting to {ws_url}")

        while True:
            try:
                async with websockets.connect(ws_url) as ws:
                    self._ws = ws
                    l.info(f"NapCat [{self.instance_id}] connected")
                    await self._listen(ws)
            except websockets.exceptions.ConnectionClosedOK:
                l.info(f"NapCat [{self.instance_id}] connection closed normally")
            except Exception as e:
                l.error(f"NapCat [{self.instance_id}] connection error: {e}")
            finally:
                self._ws = None

            l.info(f"NapCat [{self.instance_id}] reconnecting in 5 s…")
            await asyncio.sleep(5)

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def _listen(self, ws):
        async for raw in ws:
            try:
                data = json.loads(raw)
                await self._handle(data)
            except json.JSONDecodeError:
                l.warning(f"NapCat [{self.instance_id}] invalid JSON received")
            except Exception as e:
                l.error(f"NapCat [{self.instance_id}] handler error: {e}")

    async def _handle(self, data: dict):
        # Action responses carry an "echo" field — ignore them
        if data.get("post_type") is None:
            return

        if data.get("post_type") != "message":
            return

        if data.get("message_type") == "group":
            await self._on_group_message(data)

    async def _on_group_message(self, event: dict):
        # NapCat echoes the bot's own sent messages back as real events;
        # self_id is the bot's QQ number, present on every OneBot 11 event.
        if event.get("user_id") == event.get("self_id"):
            return

        group_id = str(event.get("group_id", ""))
        user_id = str(event.get("user_id", ""))
        sender = event.get("sender", {})
        # Prefer group card (nickname-in-group) over global nickname
        nickname = sender.get("card") or sender.get("nickname") or user_id

        text, attachments = self._parse_message(event)
        if not text.strip() and not attachments:
            return

        # QQ avatar endpoint (public, no auth)
        avatar_url = f"https://q.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640"

        msg = NormalizedMessage(
            platform="napcat",
            instance_id=self.instance_id,
            channel={"group_id": group_id},
            user=nickname,
            user_id=user_id,
            user_avatar=avatar_url,
            text=text,
            attachments=attachments,
        )
        await self.bridge.on_message(msg)

    @staticmethod
    def _parse_message(event: dict) -> tuple[str, list[Attachment]]:
        """
        Parse an OneBot 11 message event into plain text + attachments.
        Always uses the structured ``message`` segment array; CQ-code strings
        in ``raw_message`` are only used as a last-resort text fallback.
        """
        segments = event.get("message", [])

        # If NapCat sent a plain string instead of an array, treat as text only
        if isinstance(segments, str):
            return segments, []

        text_parts: list[str] = []
        attachments: list[Attachment] = []

        for seg in segments:
            t = seg.get("type", "")
            d = seg.get("data", {})

            if t == "text":
                text_parts.append(d.get("text", ""))

            elif t == "at":
                name = d.get("name") or d.get("qq", "")
                text_parts.append(f"@{name}")

            elif t == "image":
                url = d.get("url") or d.get("file", "")
                name = d.get("file", "image.jpg")
                attachments.append(Attachment(type="image", url=url, name=name))

            elif t == "record":  # voice message
                url = d.get("url") or d.get("file", "")
                name = d.get("file", "voice.amr")
                attachments.append(Attachment(type="voice", url=url, name=name))

            elif t == "video":
                url = d.get("url") or d.get("file", "")
                name = d.get("file", "video.mp4")
                attachments.append(Attachment(type="video", url=url, name=name))

            elif t == "file":
                url = d.get("url") or d.get("path", "")
                name = d.get("name", "file")
                try:
                    size = int(d.get("size", -1))
                except (TypeError, ValueError):
                    size = -1
                attachments.append(Attachment(type="file", url=url, name=name, size=size))

            elif t == "face":
                face_id_raw = d.get("id", "")
                gif_data = _load_face_gif(face_id_raw)
                if gif_data is not None:
                    # face_id is validated integer at this point
                    name = f"face_{int(face_id_raw)}.gif"
                    attachments.append(Attachment(type="image", url="", name=name, data=gif_data))

            # reply, forward, mface, etc. — silently skip

        text = "".join(text_parts)
        # If segments gave us nothing useful, fall back to raw_message string
        if not text and not attachments:
            text = event.get("raw_message", "")

        return text, attachments

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
        group_id = channel.get("group_id")
        if not group_id:
            l.warning(f"NapCat [{self.instance_id}] send: no group_id in channel {channel}")
            return

        if self._ws is None:
            l.warning(f"NapCat [{self.instance_id}] send: not connected, message dropped")
            return

        max_size: int = self.config.get("max_file_size", _DEFAULT_MAX)
        segments: list[dict] = []

        rich_header = kwargs.get("rich_header")
        if rich_header:
            t, c = rich_header.get("title", ""), rich_header.get("content", "")
            prefix = f"[{t}" + (f" · {c}" if c else "") + "]"
            text = f"{prefix}\n{text}" if text else prefix

        if text:
            segments.append({"type": "text", "data": {"text": text}})

        for att in (attachments or []):
            if not att.url and att.data is None:
                continue

            if att.type == "image":
                # Download through the bridge so NapCat doesn't need to reach
                # external CDNs (e.g. Discord CDN, Telegram API) directly.
                # fetch_attachment() uses att.data directly if already loaded
                # (e.g. a face GIF), otherwise downloads from att.url.
                result = await media.fetch_attachment(att, max_size)
                if result:
                    data_bytes, _ = result
                    b64 = base64.b64encode(data_bytes).decode()
                    segments.append({"type": "image", "data": {"file": f"base64://{b64}"}})
                else:
                    segments.append({"type": "text", "data": {"text": f"\n[图片] {att.url or att.name}"}})

            elif att.type == "voice":
                result = await media.fetch_attachment(att, max_size)
                if result:
                    data_bytes, _ = result
                    b64 = base64.b64encode(data_bytes).decode()
                    segments.append({"type": "record", "data": {"file": f"base64://{b64}"}})
                else:
                    segments.append({"type": "text", "data": {"text": f"\n[语音] {att.url or att.name}"}})

            elif att.type == "video":
                result = await media.fetch_attachment(att, max_size)
                if result:
                    data_bytes, _ = result
                    b64 = base64.b64encode(data_bytes).decode()
                    segments.append({"type": "video", "data": {"file": f"base64://{b64}"}})
                else:
                    segments.append({"type": "text", "data": {"text": f"\n[视频] {att.url or att.name}"}})

            else:  # file — QQ file upload is complex; send URL as text
                label = att.url or att.name
                segments.append({"type": "text", "data": {"text": f"\n[文件: {att.name}] {label}"}})

        if not segments:
            return

        payload = {
            "action": "send_group_msg",
            "params": {
                "group_id": int(group_id),
                "message": segments,
            },
            "echo": str(uuid.uuid4()),
        }

        try:
            await self._ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            l.error(f"NapCat [{self.instance_id}] send failed: {e}")
