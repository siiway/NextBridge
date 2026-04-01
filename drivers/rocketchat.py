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
#   rc_alias  – Display name override  (e.g. "{user}")
#   rc_avatar – Avatar URL override    (e.g. "{user_avatar}", must be HTTPS)

from drivers.registry import register
import asyncio

import aiohttp
from aiohttp import web
from aiohttp_socks import ProxyConnector
from pydantic import model_validator

import services.logger as log
import services.media as media
from services.message import Attachment, NormalizedMessage
from services.config_schema import _DriverConfig
from services.config import get_proxy, UNSET
from drivers import BaseDriver


class RocketChatConfig(_DriverConfig):
    send_method: str = "api"  # "api" or "webhook"
    # API send mode (and receive attachment downloads)
    server_url: str = ""
    auth_token: str = ""
    user_id: str = ""
    # Webhook send mode
    webhook_url: str = ""
    # Listener (receive side)
    listen_port: int = 8093
    listen_path: str = "/rocketchat/webhook"
    webhook_token: str = ""
    max_file_size: int = 50 * 1024 * 1024
    proxy: str | None = UNSET

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


logger = log.get_logger()


class RocketChatDriver(BaseDriver[RocketChatConfig]):
    def __init__(self, instance_id: str, config: RocketChatConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._session: aiohttp.ClientSession | None = None
        self._username_cache: dict[str, str] = {}
        self._proxy = get_proxy(config.proxy)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        if self._proxy:
            connector = ProxyConnector.from_url(self._proxy, rdns=True)
            logger.info(f"Rocket.Chat [{self.instance_id}] use proxy {self._proxy}")
        else:
            connector = aiohttp.TCPConnector(ssl=True)

        self._session = aiohttp.ClientSession(connector=connector)
        self.bridge.register_sender(self.instance_id, self.send)

        app = web.Application()
        app.router.add_post(self.config.listen_path, self._handle_webhook)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.config.listen_port)
        await site.start()
        logger.info(
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
            "X-User-Id": self.config.user_id,
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
                logger.warning(
                    f"Rocket.Chat [{self.instance_id}] webhook token mismatch"
                )
                return web.json_response({"error": "forbidden"}, status=403)

        sender_id: str = body.get("user_id", "")
        if sender_id == self.config.user_id:
            return web.json_response({})

        text: str = body.get("text", "").strip()
        room_id: str = body.get("channel_id") or body.get("rid", "")
        username: str = body.get("user_name", sender_id)
        avatar: str = body.get("user_avatar", "")
        server: str = self.config.server_url.rstrip("/")

        mentions = []
        raw_mentions = body.get("mentions", [])
        for m in raw_mentions:
            uid = m.get("_id")
            uname = m.get("username")
            if uid and uname:
                mentions.append({"id": uid, "name": uname})

        attachments: list[Attachment] = []
        for att_raw in body.get("attachments") or []:
            att = await self._parse_attachment(
                att_raw, server, self.config.max_file_size
            )
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
            mentions=mentions,
            source_proxy=self._proxy,
        )
        asyncio.create_task(self.bridge.on_message(normalized))
        return web.json_response({})

    async def _parse_attachment(
        self, att_raw: dict, server: str, max_size: int
    ) -> Attachment | None:
        title = att_raw.get("title") or att_raw.get("description") or "attachment"
        image_url = att_raw.get("image_url", "")
        video_url = att_raw.get("video_url", "")
        audio_url = att_raw.get("audio_url", "")
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
                    return Attachment(
                        type=att_type, url=url, name=title, size=-1, data=None
                    )
                data = await resp.read()
                if len(data) > max_size:
                    logger.debug(
                        f"Rocket.Chat [{self.instance_id}] attachment "
                        f"{title!r} exceeds size limit, skipping data"
                    )
                    return Attachment(
                        type=att_type, url=url, name=title, size=len(data), data=None
                    )
                return Attachment(
                    type=att_type, url="", name=title, size=len(data), data=data
                )
        except Exception as e:
            logger.warning(
                f"Rocket.Chat [{self.instance_id}] attachment download failed: {e}"
            )
            return Attachment(type=att_type, url=url, name=title, size=-1, data=None)

    async def _get_username(self, user_id: str, server: str) -> str:
        if user_id in self._username_cache:
            return self._username_cache[user_id]
        if self._session is None or not self.config.auth_token:
            return ""

        username = ""
        try:
            async with self._session.get(
                f"{server}/api/v1/users.info",
                params={"userId": user_id},
                headers=self._auth_headers,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    u = data.get("user", {})
                    username = u.get("username", "")
        except Exception:
            pass

        if username:
            self._username_cache[user_id] = username
        return username

    # ------------------------------------------------------------------
    # Send — dispatcher
    # ------------------------------------------------------------------

    async def send(
        self,
        channel: dict,
        text: str,
        attachments: list[Attachment] | None = None,
        **kwargs,
    ):
        reply_to_id = kwargs.get("reply_to_id")

        if self._session is None:
            logger.warning(f"Rocket.Chat [{self.instance_id}] send: driver not started")
            return

        alias = kwargs.get("rc_alias", "")
        av_url = kwargs.get("rc_avatar", "")
        avatar = av_url if (av_url and av_url.startswith("https://")) else ""
        server = self.config.server_url.rstrip("/")

        # Handle mentions: replace @Name with @username
        mentions = kwargs.get("mentions", [])
        for m in mentions:
            username = await self._get_username(m["id"], server)
            if username:
                text = text.replace(f"@{m['name']}", f"@{username}")

        if self.config.send_method == "webhook":
            await self._send_webhook(text, attachments, alias, avatar, reply_to_id)
        else:
            room_id = channel.get("room_id", "")
            if not room_id:
                logger.warning(
                    f"Rocket.Chat [{self.instance_id}] send: "
                    f"no room_id in channel {channel}"
                )
                return
            server = self.config.server_url.rstrip("/")
            await self._send_api(
                server, room_id, text, attachments, alias, avatar, reply_to_id
            )

    # ------------------------------------------------------------------
    # Send — API mode
    # ------------------------------------------------------------------

    async def _send_api(
        self,
        server: str,
        room_id: str,
        text: str,
        attachments: list[Attachment] | None,
        alias: str,
        avatar: str,
        reply_to_id: str | None = None,
    ) -> None:

        if text.strip():
            await self._api_post_message(
                server, room_id, text, alias, avatar, reply_to_id
            )

        for att in attachments or []:
            if not att.url and att.data is None:
                continue
            result = await media.fetch_attachment(
                att, self.config.max_file_size, self._proxy
            )
            if not result:
                label = att.name or att.url or ""
                await self._api_post_message(
                    server,
                    room_id,
                    f"[{att.type.capitalize()}: {label}]",
                    alias,
                    avatar,
                    reply_to_id,
                )
                continue
            data_bytes, mime = result
            fname = media.filename_for(att.name, mime)
            await self._api_upload_file(
                server, room_id, data_bytes, fname, mime, reply_to_id
            )

    async def _api_post_message(
        self,
        server: str,
        room_id: str,
        text: str,
        alias: str = "",
        avatar: str = "",
        reply_to_id: str | None = None,
    ) -> None:
        assert self._session is not None  # Type narrowing - session is set in start()
        payload: dict = {"roomId": room_id, "text": text}
        if reply_to_id:
            payload["tmid"] = reply_to_id
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
                    logger.error(
                        f"Rocket.Chat [{self.instance_id}] post failed "
                        f"HTTP {resp.status}: {body[:200]}"
                    )
        except Exception as e:
            logger.error(f"Rocket.Chat [{self.instance_id}] post error: {e}")

    async def _api_upload_file(
        self,
        server: str,
        room_id: str,
        data: bytes,
        fname: str,
        mime: str,
        reply_to_id: str | None = None,
    ) -> None:
        assert self._session is not None  # Type narrowing - session is set in start()
        form = aiohttp.FormData()
        if reply_to_id:
            form.add_field("tmid", reply_to_id)
        form.add_field("file", data, filename=fname, content_type=mime)
        try:
            async with self._session.post(
                f"{server}/api/v1/rooms.upload/{room_id}",
                data=form,
                headers=self._auth_headers,
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    logger.error(
                        f"Rocket.Chat [{self.instance_id}] file upload failed "
                        f"HTTP {resp.status}: {body[:200]}"
                    )
        except Exception as e:
            logger.error(f"Rocket.Chat [{self.instance_id}] file upload error: {e}")

    # ------------------------------------------------------------------
    # Send — Webhook mode
    # ------------------------------------------------------------------

    async def _send_webhook(
        self,
        text: str,
        attachments: list[Attachment] | None,
        username: str,
        icon_url: str,
        reply_to_id: str | None = None,
    ) -> None:
        assert self._session is not None  # Type narrowing - session is set in start()

        # Build RC webhook attachment objects for each media item.
        # Incoming webhooks cannot upload bytes, so we use URL-based rendering
        # where possible and fall back to text labels for byte-only attachments.
        wh_attachments: list[dict] = []
        fallback_labels: list[str] = []

        for att in attachments or []:
            if not att.url and att.data is None:
                continue
            if att.url:
                entry: dict = {"title": att.name or att.url}
                if att.type == "image":
                    entry["image_url"] = att.url
                    entry["title_link"] = att.url
                else:
                    entry["title_link"] = att.url
                wh_attachments.append(entry)
            else:
                # bytes only, no URL — can't render via incoming webhook
                fallback_labels.append(
                    f"[{att.type.capitalize()}: {att.name or 'attachment'}]"
                )

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
        if reply_to_id:
            payload["tmid"] = reply_to_id

        try:
            async with self._session.post(
                self.config.webhook_url, json=payload
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    logger.error(
                        f"Rocket.Chat [{self.instance_id}] webhook post failed "
                        f"HTTP {resp.status}: {body[:200]}"
                    )
        except Exception as e:
            logger.error(f"Rocket.Chat [{self.instance_id}] webhook post error: {e}")


register("rocketchat", RocketChatConfig, RocketChatDriver)
