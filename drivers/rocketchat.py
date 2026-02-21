# Rocket.Chat driver via Outgoing Webhook + REST API or Incoming Webhook.
#
# Receive: Rocket.Chat pushes events to an HTTP endpoint you expose via an
#          Outgoing Webhook integration.  Configure one in
#          Administration → Integrations → New → Outgoing Webhook:
#            Event Trigger : Message Sent
#            Channel       : (leave blank for all, or enter specific channels)
#            URLs          : http(s)://<host>:<listen_port><listen_path>
#            Token         : (copy to webhook_token in config)
#
# Send (send_method = "api", default):
#          Uses the REST API (chat.postMessage / rooms.upload).
#          Supports per-message alias/avatar via rc_alias / rc_avatar rule keys.
#          File attachments are uploaded directly to the server.
#
# Send (send_method = "webhook"):
#          POSTs to a Rocket.Chat Incoming Webhook URL.
#          Supports per-message username/avatar via rc_alias / rc_avatar rule keys.
#          File attachments with a public URL are rendered inline via the
#          webhook attachments payload.  Byte-only attachments fall back to
#          text labels (incoming webhooks cannot upload files).
#
# Config keys (under rocketchat.<instance_id>):
#   send_method    – "api" (default) or "webhook"
#   server_url     – Full base URL of the RC server (required for send_method="api";
#                    also used for receive-side attachment downloads)
#   auth_token     – Personal access token  (required for send_method="api")
#   user_id        – Bot account user ID    (required for send_method="api")
#   webhook_url    – Incoming Webhook URL   (required for send_method="webhook")
#   listen_port    – HTTP port for the outgoing webhook listener (default: 8093)
#   listen_path    – HTTP path for the outgoing webhook listener (default: "/rocketchat/webhook")
#   webhook_token  – Outgoing webhook token for request verification (recommended)
#   max_file_size  – Max bytes per attachment when sending (default: 50 MB)
#
# Rule channel keys:
#   room_id – Rocket.Chat room ID  (required for send_method="api")
#             e.g. "GENERAL" or the _id from /api/v1/channels.info?roomName=general
#
# Per-message identity (add to the rule's msg block):
#   rc_alias  – Display name override  (e.g. "{username}")
#   rc_avatar – Avatar URL override    (e.g. "{user_avatar}", must be HTTPS)

import asyncio

import aiohttp
from aiohttp import web
from pydantic import model_validator

import services.logger as log
import services.media as media
from services.message import Attachment, NormalizedMessage
from services.config_schema import _DriverConfig
from drivers import BaseDriver


class RocketChatConfig(_DriverConfig):
    send_method:   str = "api"   # "api" or "webhook"
    # API send mode (and receive attachment downloads)
    server_url:    str = ""
    auth_token:    str = ""
    user_id:       str = ""
    # Webhook send mode
    webhook_url:   str = ""
    # Listener (receive side)
    listen_port:   int = 8093
    listen_path:   str = "/rocketchat/webhook"
    webhook_token: str = ""
    max_file_size: int = 50 * 1024 * 1024

    @model_validator(mode="after")
    def _check_send_config(self) -> "RocketChatConfig":
        if self.send_method == "api":
            if not self.server_url or not self.auth_token or not self.user_id:
                raise ValueError(
                    "send_method='api' requires server_url, auth_token, and user_id"
                )
        elif self.send_method == "webhook":
            if not self.webhook_url:
                raise ValueError("send_method='webhook' requires webhook_url")
        else:
            raise ValueError("send_method must be 'api' or 'webhook'")
        return self


l = log.get_logger()


class RocketChatDriver(BaseDriver[RocketChatConfig]):

    def __init__(self, instance_id: str, config: RocketChatConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self._session = aiohttp.ClientSession()
        self.bridge.register_sender(self.instance_id, self.send)

        app = web.Application()
        app.router.add_post(self.config.listen_path, self._handle_webhook)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.config.listen_port)
        await site.start()
        l.info(
            f"Rocket.Chat [{self.instance_id}] listening on "
            f"0.0.0.0:{self.config.listen_port}{self.config.listen_path} "
            f"(send_method={self.config.send_method})"
        )
        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()
            await self._session.close()
            self._session = None

    @property
    def _auth_headers(self) -> dict:
        return {
            "X-Auth-Token": self.config.auth_token,
            "X-User-Id":    self.config.user_id,
        }

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "bad request"}, status=400)

        if self.config.webhook_token:
            if body.get("token", "") != self.config.webhook_token:
                l.warning(f"Rocket.Chat [{self.instance_id}] webhook token mismatch")
                return web.json_response({"error": "forbidden"}, status=403)

        sender_id: str = body.get("user_id", "")
        if sender_id == self.config.user_id:
            return web.json_response({})

        text:     str = body.get("text", "").strip()
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
        title      = att_raw.get("title") or att_raw.get("description") or "attachment"
        image_url  = att_raw.get("image_url", "")
        video_url  = att_raw.get("video_url", "")
        audio_url  = att_raw.get("audio_url", "")
        title_link = att_raw.get("title_link", "")

        if image_url:
            raw_url, att_type = image_url, "image"
        elif video_url:
            raw_url, att_type = video_url, "video"
        elif audio_url:
            raw_url, att_type = audio_url, "voice"
        elif title_link:
            raw_url, att_type = title_link, "file"
        else:
            return None

        url = raw_url if raw_url.startswith("http") else f"{server}{raw_url}"

        # Download with bot credentials when available (RC files require auth)
        if self._session is None or not self.config.auth_token:
            return Attachment(type=att_type, url=url, name=title, size=-1, data=None)

        try:
            async with self._session.get(url, headers=self._auth_headers) as resp:
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
    # Send — dispatcher
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

        alias  = kwargs.get("rc_alias", "")
        av_url = kwargs.get("rc_avatar", "")
        avatar = av_url if (av_url and av_url.startswith("https://")) else ""

        if self.config.send_method == "webhook":
            await self._send_webhook(text, attachments, alias, avatar)
        else:
            room_id = channel.get("room_id", "")
            if not room_id:
                l.warning(
                    f"Rocket.Chat [{self.instance_id}] send: "
                    f"no room_id in channel {channel}"
                )
                return
            server = self.config.server_url.rstrip("/")
            await self._send_api(server, room_id, text, attachments, alias, avatar)

    # ------------------------------------------------------------------
    # Send — API mode
    # ------------------------------------------------------------------

    async def _send_api(
        self,
        server:      str,
        room_id:     str,
        text:        str,
        attachments: list[Attachment] | None,
        alias:       str,
        avatar:      str,
    ) -> None:
        max_size = self.config.max_file_size

        if text.strip():
            await self._api_post_message(server, room_id, text, alias, avatar)

        for att in (attachments or []):
            if not att.url and att.data is None:
                continue
            result = await media.fetch_attachment(att, max_size)
            if not result:
                label = att.name or att.url or ""
                await self._api_post_message(
                    server, room_id,
                    f"[{att.type.capitalize()}: {label}]",
                    alias, avatar,
                )
                continue
            data_bytes, mime = result
            fname = media.filename_for(att.name, mime)
            await self._api_upload_file(server, room_id, data_bytes, fname, mime)

    async def _api_post_message(
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
                headers=self._auth_headers,
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    l.error(
                        f"Rocket.Chat [{self.instance_id}] post failed "
                        f"HTTP {resp.status}: {body[:200]}"
                    )
        except Exception as e:
            l.error(f"Rocket.Chat [{self.instance_id}] post error: {e}")

    async def _api_upload_file(
        self, server: str, room_id: str, data: bytes, fname: str, mime: str
    ) -> None:
        form = aiohttp.FormData()
        form.add_field("file", data, filename=fname, content_type=mime)
        try:
            async with self._session.post(
                f"{server}/api/v1/rooms.upload/{room_id}",
                data=form,
                headers=self._auth_headers,
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    l.error(
                        f"Rocket.Chat [{self.instance_id}] file upload failed "
                        f"HTTP {resp.status}: {body[:200]}"
                    )
        except Exception as e:
            l.error(f"Rocket.Chat [{self.instance_id}] file upload error: {e}")

    # ------------------------------------------------------------------
    # Send — Webhook mode
    # ------------------------------------------------------------------

    async def _send_webhook(
        self,
        text:        str,
        attachments: list[Attachment] | None,
        username:    str,
        icon_url:    str,
    ) -> None:
        max_size = self.config.max_file_size

        # Build RC webhook attachment objects for each media item.
        # Incoming webhooks cannot upload bytes, so we use URL-based rendering
        # where possible and fall back to text labels for byte-only attachments.
        wh_attachments: list[dict] = []
        fallback_labels: list[str] = []

        for att in (attachments or []):
            if not att.url and att.data is None:
                continue
            if att.url:
                entry: dict = {"title": att.name or att.url}
                if att.type == "image":
                    entry["image_url"]  = att.url
                    entry["title_link"] = att.url
                else:
                    entry["title_link"] = att.url
                wh_attachments.append(entry)
            else:
                # bytes only, no URL — can't render via incoming webhook
                fallback_labels.append(f"[{att.type.capitalize()}: {att.name or 'attachment'}]")

        # Append byte-only fallback labels to the text body
        full_text = text
        if fallback_labels:
            suffix = "\n".join(fallback_labels)
            full_text = f"{full_text}\n{suffix}" if full_text else suffix

        if not full_text.strip() and not wh_attachments:
            return

        payload: dict = {}
        if full_text.strip():
            payload["text"] = full_text
        if username:
            payload["username"] = username
        if icon_url:
            payload["icon_url"] = icon_url
        if wh_attachments:
            payload["attachments"] = wh_attachments

        try:
            async with self._session.post(
                self.config.webhook_url, json=payload
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    l.error(
                        f"Rocket.Chat [{self.instance_id}] webhook post failed "
                        f"HTTP {resp.status}: {body[:200]}"
                    )
        except Exception as e:
            l.error(f"Rocket.Chat [{self.instance_id}] webhook post error: {e}")


from drivers.registry import register
register("rocketchat", RocketChatConfig, RocketChatDriver)
