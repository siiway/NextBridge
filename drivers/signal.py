# Signal driver via signal-cli REST API.
#
# Requires a running instance of signal-cli-rest-api:
#   https://github.com/bbernhard/signal-cli-rest-api
#
# Receive: WebSocket connection to GET /v1/receive/{number}
#          Streams JSON envelopes for incoming messages.
#
# Send:    POST /v2/send with JSON body.
#          Attachments are base64-encoded and included inline.
#
# Config keys (under signal.<instance_id>):
#   api_url       – Base URL of the signal-cli REST API (required),
#                   e.g. "http://localhost:8080"
#   number        – Your registered Signal phone number (required),
#                   e.g. "+12025551234"
#   max_file_size – Max bytes per attachment when sending (default 50 MB)
#
# Rule channel keys:
#   recipient – Phone number for 1-on-1 chats (e.g. "+12025551234")
#               or "group.<base64id>" for group chats

import asyncio
import base64
import json
import mimetypes

import aiohttp

import services.logger as log
import services.media as media
from services.message import Attachment, NormalizedMessage
from services.config_schema import _DriverConfig
from drivers import BaseDriver


class SignalConfig(_DriverConfig):
    api_url:       str
    number:        str
    max_file_size: int = 50 * 1024 * 1024

l = log.get_logger()

def _content_type_to_att_type(ct: str) -> str:
    if ct.startswith("image/"):
        return "image"
    if ct.startswith("video/"):
        return "video"
    if ct.startswith("audio/"):
        return "voice"
    return "file"


class SignalDriver(BaseDriver[SignalConfig]):

    def __init__(self, instance_id: str, config: SignalConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        api_url = self.config.api_url.rstrip("/")
        number  = self.config.number

        self._session = aiohttp.ClientSession()
        self.bridge.register_sender(self.instance_id, self.send)

        ws_url = f"{api_url}/v1/receive/{number}"
        l.info(f"Signal [{self.instance_id}] connecting to {ws_url}")

        try:
            while True:
                try:
                    async with self._session.ws_connect(ws_url) as ws:
                        l.info(f"Signal [{self.instance_id}] connected")
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    await self._on_envelope(json.loads(msg.data), api_url)
                                except Exception as e:
                                    l.error(f"Signal [{self.instance_id}] handler error: {e}")
                            elif msg.type in (
                                aiohttp.WSMsgType.CLOSE,
                                aiohttp.WSMsgType.ERROR,
                                aiohttp.WSMsgType.CLOSED,
                            ):
                                break
                except aiohttp.ClientError as e:
                    l.error(f"Signal [{self.instance_id}] connection error: {e}")

                l.info(f"Signal [{self.instance_id}] reconnecting in 5 s…")
                await asyncio.sleep(5)
        finally:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def _on_envelope(self, data: dict, api_url: str) -> None:
        envelope = data.get("envelope", {})
        dm = envelope.get("dataMessage")
        if dm is None:
            return  # read receipt, typing indicator, etc.

        text = dm.get("message") or ""
        raw_attachments: list[dict] = dm.get("attachments", [])

        if not text.strip() and not raw_attachments:
            return

        # Channel: group or 1-on-1
        group_info = dm.get("groupInfo")
        if group_info and group_info.get("groupId"):
            channel = {"recipient": f"group.{group_info['groupId']}"}
        else:
            channel = {"recipient": envelope.get("source", "")}

        sender     = envelope.get("sourceName") or envelope.get("source", "")
        sender_id  = envelope.get("source", "")

        # Download attachments eagerly so downstream platforms can re-upload them
        attachments: list[Attachment] = []
        max_size: int = self.config.max_file_size
        for att_info in raw_attachments:
            att_id   = att_info.get("id", "")
            ct       = att_info.get("contentType", "application/octet-stream")
            fname    = att_info.get("filename") or self._fallback_name(ct)
            att_type = _content_type_to_att_type(ct)
            size     = att_info.get("size", -1)

            att_data: bytes | None = None
            if att_id and self._session is not None:
                try:
                    async with self._session.get(f"{api_url}/v1/attachments/{att_id}") as resp:
                        if resp.status == 200:
                            raw = await resp.read()
                            if len(raw) <= max_size:
                                att_data = raw
                except Exception as e:
                    l.warning(f"Signal [{self.instance_id}] attachment download failed: {e}")

            attachments.append(
                Attachment(type=att_type, url="", name=fname, size=size, data=att_data)
            )

        normalized = NormalizedMessage(
            platform="signal",
            instance_id=self.instance_id,
            channel=channel,
            user=sender,
            user_id=sender_id,
            user_avatar="",
            text=text,
            attachments=attachments,
        )
        await self.bridge.on_message(normalized)

    @staticmethod
    def _fallback_name(content_type: str) -> str:
        ext = mimetypes.guess_extension(content_type) or ""
        return f"attachment{ext}"

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
        recipient = channel.get("recipient")
        if not recipient:
            l.warning(f"Signal [{self.instance_id}] send: no recipient in channel {channel}")
            return
        if self._session is None:
            l.warning(f"Signal [{self.instance_id}] send: driver not started")
            return

        api_url = self.config.api_url.rstrip("/")
        number  = self.config.number
        max_size: int = self.config.max_file_size

        rich_header = kwargs.get("rich_header")
        if rich_header:
            t, c = rich_header.get("title", ""), rich_header.get("content", "")
            prefix = f"[{t}" + (f" · {c}" if c else "") + "]"
            text = f"{prefix}\n{text}" if text else prefix

        payload: dict = {
            "message":    text,
            "number":     number,
            "recipients": [recipient],
        }

        b64_atts: list[str] = []
        for att in (attachments or []):
            if not att.url and att.data is None:
                continue
            result = await media.fetch_attachment(att, max_size)
            if result:
                data_bytes, mime = result
                b64_atts.append(
                    f"data:{mime};base64,{base64.b64encode(data_bytes).decode()}"
                )
            else:
                label = att.name or att.url or ""
                payload["message"] += f"\n[{att.type.capitalize()}: {label}]"

        if b64_atts:
            payload["base64_attachments"] = b64_atts

        try:
            async with self._session.post(f"{api_url}/v2/send", json=payload) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    l.error(
                        f"Signal [{self.instance_id}] send failed "
                        f"HTTP {resp.status}: {body}"
                    )
        except Exception as e:
            l.error(f"Signal [{self.instance_id}] send error: {e}")


from drivers.registry import register
register("signal", SignalConfig, SignalDriver)
