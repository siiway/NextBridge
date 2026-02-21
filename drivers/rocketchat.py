# Rocket.Chat driver via Outgoing Webhook + REST API.
#
# Receive: Rocket.Chat pushes events to an HTTP endpoint you expose via an
#          Outgoing Webhook integration.  Configure one in
#          Administration → Integrations → New → Outgoing Webhook:
#            Event Trigger : Message Sent
#            Channel       : (leave blank for all, or enter specific channels)
#            URLs          : http(s)://<host>:<listen_port><listen_path>
#            Token         : (copy to webhook_token in config)
#
# Send:    Rocket.Chat REST API.  Messages are posted via chat.postMessage;
#          files are uploaded via rooms.upload.
#
# Config keys (under rocketchat.<instance_id>):
#   server_url     – Full base URL of the RC server, e.g. "https://chat.example.com"
#   auth_token     – Personal access token  (required)
#   user_id        – Bot account user ID    (required)
#   listen_port    – HTTP port for incoming webhook  (default: 8093)
#   listen_path    – HTTP path for incoming webhook  (default: "/rocketchat/webhook")
#   webhook_token  – Outgoing webhook token for request verification (recommended)
#   max_file_size  – Max bytes per attachment when sending (default: 50 MB)
#
# Rule channel keys:
#   room_id – Rocket.Chat room ID (alphanumeric, e.g. "GENERAL" or "abc123xyz")
#
# Finding room_id: In the browser, open the channel and look at the URL:
#   https://chat.example.com/channel/general  →  use the REST API
#   GET /api/v1/channels.info?roomName=general  →  body.channel._id

import asyncio
import json

import aiohttp
from aiohttp import web

import services.logger as log
import services.media as media
from services.message import Attachment, NormalizedMessage
from services.config_schema import _DriverConfig
from drivers import BaseDriver


class RocketChatConfig(_DriverConfig):
    server_url:    str
    auth_token:    str
    user_id:       str
    listen_port:   int = 8093
    listen_path:   str = "/rocketchat/webhook"
    webhook_token: str = ""
    max_file_size: int = 50 * 1024 * 1024


l = log.get_logger()


class RocketChatDriver(BaseDriver[RocketChatConfig]):

    def __init__(self, instance_id: str, config: RocketChatConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self._session = aiohttp.ClientSession(headers={
            "X-Auth-Token": self.config.auth_token,
            "X-User-Id":    self.config.user_id,
        })
        self.bridge.register_sender(self.instance_id, self.send)

        app = web.Application()
        app.router.add_post(self.config.listen_path, self._handle_webhook)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.config.listen_port)
        await site.start()
        l.info(
            f"Rocket.Chat [{self.instance_id}] listening on "
            f"0.0.0.0:{self.config.listen_port}{self.config.listen_path}"
        )
        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "bad request"}, status=400)

        # Verify webhook token if configured
        if self.config.webhook_token:
            if body.get("token", "") != self.config.webhook_token:
                l.warning(f"Rocket.Chat [{self.instance_id}] webhook token mismatch")
                return web.json_response({"error": "forbidden"}, status=403)

        # Skip bot's own messages
        sender_id: str = body.get("user_id", "")
        if sender_id == self.config.user_id:
            return web.json_response({})

        text:     str = body.get("text", "").strip()
        # channel_id is the room ID in the outgoing webhook payload
        room_id:  str = body.get("channel_id") or body.get("rid", "")
        username: str = body.get("user_name", sender_id)
        avatar:   str = body.get("user_avatar", "")
        server:   str = self.config.server_url.rstrip("/")

        max_size = self.config.max_file_size
        attachments: list[Attachment] = []
        for att_raw in (body.get("attachments") or []):
            att = await self._parse_attachment(att_raw, server, max_size)
            if att is not None:
                attachments.append(att)

        if not text and not attachments:
            return web.json_response({})

        normalized = NormalizedMessage(
            platform="rocketchat",
            instance_id=self.instance_id,
            channel={"room_id": room_id},
            user=username,
            user_id=sender_id,
            user_avatar=avatar,
            text=text,
            attachments=attachments,
        )
        asyncio.create_task(self.bridge.on_message(normalized))
        return web.json_response({})

    async def _parse_attachment(
        self, att_raw: dict, server: str, max_size: int
    ) -> Attachment | None:
        """Parse an attachment from the outgoing webhook payload."""
        title      = att_raw.get("title") or att_raw.get("description") or "attachment"
        image_url  = att_raw.get("image_url", "")
        video_url  = att_raw.get("video_url", "")
        audio_url  = att_raw.get("audio_url", "")
        title_link = att_raw.get("title_link", "")

        # Pick the most specific URL and determine type
        if image_url:
            raw_url  = image_url
            att_type = "image"
        elif video_url:
            raw_url  = video_url
            att_type = "video"
        elif audio_url:
            raw_url  = audio_url
            att_type = "voice"
        elif title_link:
            raw_url  = title_link
            att_type = "file"
        else:
            return None

        # Make relative URLs absolute
        url = raw_url if raw_url.startswith("http") else f"{server}{raw_url}"

        if self._session is None:
            return Attachment(type=att_type, url=url, name=title, size=-1, data=None)

        # Download with bot credentials (RC files require auth)
        try:
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return Attachment(type=att_type, url=url, name=title, size=-1, data=None)
                data = await resp.read()
                if len(data) > max_size:
                    l.debug(
                        f"Rocket.Chat [{self.instance_id}] attachment "
                        f"{title!r} exceeds size limit, skipping data"
                    )
                    return Attachment(type=att_type, url=url, name=title, size=len(data), data=None)
                return Attachment(type=att_type, url="", name=title, size=len(data), data=data)
        except Exception as e:
            l.warning(f"Rocket.Chat [{self.instance_id}] attachment download failed: {e}")
            return Attachment(type=att_type, url=url, name=title, size=-1, data=None)

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def send(
        self,
        channel:     dict,
        text:        str,
        attachments: list[Attachment] | None = None,
        **kwargs,
    ):
        if self._session is None:
            l.warning(f"Rocket.Chat [{self.instance_id}] send: driver not started")
            return

        room_id = channel.get("room_id", "")
        if not room_id:
            l.warning(
                f"Rocket.Chat [{self.instance_id}] send: "
                f"no room_id in channel {channel}"
            )
            return

        server = self.config.server_url.rstrip("/")

        # Per-message sender identity — configured in the rule's msg block, e.g.
        #   "rc_alias":  "{username}",
        #   "rc_avatar": "{user_avatar}"
        alias  = kwargs.get("rc_alias", "")
        av_url = kwargs.get("rc_avatar", "")
        # RC only accepts absolute HTTPS avatar URLs
        avatar = av_url if (av_url and av_url.startswith("https://")) else ""

        if text.strip():
            await self._post_message(server, room_id, text, alias, avatar)

        max_size = self.config.max_file_size
        for att in (attachments or []):
            if not att.url and att.data is None:
                continue
            result = await media.fetch_attachment(att, max_size)
            if not result:
                label = att.name or att.url or ""
                await self._post_message(
                    server, room_id,
                    f"[{att.type.capitalize()}: {label}]",
                    alias, avatar,
                )
                continue
            data_bytes, mime = result
            fname = media.filename_for(att.name, mime)
            await self._upload_file(server, room_id, data_bytes, fname, mime)

    async def _post_message(
        self,
        server:  str,
        room_id: str,
        text:    str,
        alias:   str = "",
        avatar:  str = "",
    ) -> None:
        payload: dict = {"roomId": room_id, "text": text}
        if alias:
            payload["alias"] = alias
        if avatar:
            payload["avatar"] = avatar
        try:
            async with self._session.post(
                f"{server}/api/v1/chat.postMessage",
                json=payload,
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    l.error(
                        f"Rocket.Chat [{self.instance_id}] post failed "
                        f"HTTP {resp.status}: {body[:200]}"
                    )
        except Exception as e:
            l.error(f"Rocket.Chat [{self.instance_id}] post error: {e}")

    async def _upload_file(
        self, server: str, room_id: str, data: bytes, fname: str, mime: str
    ) -> None:
        form = aiohttp.FormData()
        form.add_field("file", data, filename=fname, content_type=mime)
        try:
            async with self._session.post(
                f"{server}/api/v1/rooms.upload/{room_id}",
                data=form,
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    l.error(
                        f"Rocket.Chat [{self.instance_id}] file upload failed "
                        f"HTTP {resp.status}: {body[:200]}"
                    )
        except Exception as e:
            l.error(f"Rocket.Chat [{self.instance_id}] file upload error: {e}")


from drivers.registry import register
register("rocketchat", RocketChatConfig, RocketChatDriver)
