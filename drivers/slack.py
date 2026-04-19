# Slack driver.
#
# Receive: two modes —
#   Socket Mode (when app_token is set)              – WebSocket; no public URL needed.
#   Events API  (when signing_secret is set)         – HTTP webhook from Slack.
#
# Send: two modes controlled by "send_method" in config —
#   "bot"     (default) – chat.postMessage + files.upload (requires bot_token).
#   "webhook"           – Incoming Webhook URL (requires incoming_webhook_url).
#                         Text-only; attachments fall back to text labels.
#                         The channel is fixed by the webhook URL; channel_id is ignored.
#
# Config keys (under slack.<instance_id>):
#   bot_token            – Bot token (xoxb-...) for Web API send and file downloads
#   app_token            – App-level token (xapp-...) for Socket Mode receive
#   send_method          – "bot" (default) | "webhook"
#   incoming_webhook_url – Incoming Webhook URL for send_method="webhook"
#   signing_secret       – Slack signing secret for Events API signature verification
#   listen_path          – HTTP path for Events API (default: "/slack/events")
#   max_file_size        – Max bytes per attachment when sending (default 50 MB)
#
# Rule channel keys:
#   channel_id – Slack channel ID, e.g. "C1234567890"
#                (ignored when send_method="webhook"; channel is fixed by the webhook URL)

import asyncio
import hashlib
import hmac as _hmac
import json
import time
from typing import Literal

import aiohttp
from aiohttp_socks import ProxyConnector
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.async_client import AsyncBaseSocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web.async_client import AsyncWebClient

import services.logger as log
from drivers import BaseDriver
from drivers.registry import register
from services import media
from services.config import UNSET, get_proxy
from services.config_schema import _DriverConfig
from services.message import Attachment, NormalizedMessage


class SlackConfig(_DriverConfig):
    bot_token: str = ""
    app_token: str = ""
    send_method: Literal["bot", "webhook"] = "bot"
    incoming_webhook_url: str = ""
    signing_secret: str = ""
    listen_path: str = "/slack/events"
    max_file_size: int = 50 * 1024 * 1024
    proxy: str | None = UNSET


logger = log.get_logger()


def _mime_to_att_type(mime: str) -> str:
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "voice"
    return "file"


def _verify_slack_signature(signing_secret: str, headers, body: bytes) -> bool:
    """Verify X-Slack-Signature against the request body using HMAC-SHA256."""
    timestamp = headers.get("X-Slack-Request-Timestamp", "")
    signature = headers.get("X-Slack-Signature", "")
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except (ValueError, TypeError):
        return False
    base = f"v0:{timestamp}:{body.decode('utf-8', errors='replace')}"
    expected = (
        "v0="
        + _hmac.new(
            signing_secret.encode(),
            base.encode(),
            hashlib.sha256,
        ).hexdigest()
    )
    return _hmac.compare_digest(expected, signature)


class SlackDriver(BaseDriver[SlackConfig]):
    def __init__(self, instance_id: str, config: SlackConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._web: AsyncWebClient | None = None
        self._sm: SocketModeClient | None = None
        self._session: aiohttp.ClientSession | None = None
        self._user_cache: dict[
            str, tuple[str, str]
        ] = {}  # user_id → (name, avatar_url)
        self._proxy = get_proxy(config.proxy)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        bot_token = self.config.bot_token
        app_token = self.config.app_token
        send_method = self.config.send_method
        webhook_url = self.config.incoming_webhook_url
        signing_secret = self.config.signing_secret
        listen_path = self.config.listen_path

        if self._proxy:
            connector = ProxyConnector.from_url(self._proxy, rdns=True)
            logger.info(f"Slack [{self.instance_id}] use proxy {self._proxy}")
        else:
            connector = aiohttp.TCPConnector(ssl=True)

        # Register early so the bridge can route to us; individual send helpers
        # guard against uninitialized state.
        self.bridge.register_sender(self.instance_id, self.send)
        self._session = aiohttp.ClientSession(connector=connector)

        if bot_token:
            self._web = AsyncWebClient(token=bot_token, session=self._session)

        # ------ Socket Mode receive (preferred when app_token is present) ----
        if app_token:
            self._sm = SocketModeClient(
                app_token=app_token,
                web_client=self._web,
                auto_reconnect_enabled=True,
            )
            self._sm.socket_mode_request_listeners.append(self._on_request)
            try:
                await self._sm.connect_to_new_endpoint()
                logger.info(f"Slack [{self.instance_id}] Socket Mode connected")
                await asyncio.Event().wait()
            finally:
                await self._sm.close()
                await self._session.close()
            return

        # ------ Events API webhook receive -----------------------------------
        if signing_secret:
            app = FastAPI()
            app.add_api_route("/", self._handle_events_api, methods=["POST"])
            if self.http_server is None:
                logger.error(
                    f"Slack [{self.instance_id}] shared HTTP server unavailable"
                )
                return
            self.http_server.mount(self.instance_id, listen_path, app)
            logger.info(
                f"Slack [{self.instance_id}] Events API mounted at {listen_path}"
            )
            try:
                await asyncio.Event().wait()
            finally:
                await self._session.close()
            return

        # ------ Send-only mode -----------------------------------------------
        if send_method == "webhook" and not webhook_url:
            logger.error(
                f"Slack [{self.instance_id}] send_method='webhook' requires incoming_webhook_url"
            )
            return
        if send_method != "webhook" and not bot_token:
            logger.error(
                f"Slack [{self.instance_id}] send_method='bot' requires bot_token"
            )
            return
        logger.info(f"Slack [{self.instance_id}] running in send-only mode")
        # Session stays open; task completes and send() continues to work via the bridge.

    # ------------------------------------------------------------------
    # Receive — Socket Mode
    # ------------------------------------------------------------------

    async def _on_request(
        self, client: AsyncBaseSocketModeClient, req: SocketModeRequest
    ) -> None:
        # Acknowledge immediately — Slack requires this within 3 seconds
        await client.send_socket_mode_response(
            SocketModeResponse(envelope_id=req.envelope_id)
        )
        if req.type != "events_api":
            return
        event = req.payload.get("event", {})
        await self._dispatch_event(event)

    # ------------------------------------------------------------------
    # Receive — Events API (HTTP webhook)
    # ------------------------------------------------------------------

    async def _handle_events_api(
        self, request: Request
    ) -> JSONResponse | PlainTextResponse:
        body = await request.body()

        if self.config.signing_secret and not _verify_slack_signature(
            self.config.signing_secret, request.headers, body
        ):
            return PlainTextResponse("Invalid signature", status_code=403)

        try:
            payload = json.loads(body)
        except Exception:
            return PlainTextResponse("Bad JSON", status_code=400)

        # URL verification challenge (sent by Slack when the endpoint is first saved)
        if payload.get("type") == "url_verification":
            return JSONResponse({"challenge": payload.get("challenge", "")})

        event = payload.get("event", {})
        asyncio.create_task(self._dispatch_event(event))
        return PlainTextResponse("ok", status_code=200)

    # ------------------------------------------------------------------
    # Receive — shared event dispatch
    # ------------------------------------------------------------------

    async def _dispatch_event(self, event: dict) -> None:
        if not isinstance(event, dict):
            return
        if event.get("type") != "message":
            return
        # Ignore bot messages (including our own) and non-plain subtypes
        # (message_changed, channel_join, etc.)
        if event.get("bot_id") or event.get("subtype"):
            return

        text = event.get("text", "")
        channel_id = event.get("channel", "")
        user_id = event.get("user", "")

        if not channel_id or not user_id:
            return

        display_name, user_avatar = await self._get_user_info(user_id)

        attachments: list[Attachment] = []
        for f in event.get("files", []):
            att = await self._download_file(f, self.config.max_file_size)
            if att is not None:
                attachments.append(att)

        if not text.strip() and not attachments:
            return

        normalized = NormalizedMessage(
            platform="slack",
            instance_id=self.instance_id,
            channel={"channel_id": channel_id},
            nickname=display_name,
            user_id=user_id,
            user_avatar=user_avatar,
            text=text,
            attachments=attachments,
            message_id=str(event.get("ts", "")),
            reply_parent=str(event.get("thread_ts", ""))
            if event.get("thread_ts")
            else None,
            source_proxy=self._media_proxy,
            username=display_name,
        )
        await self.bridge.on_message(normalized)

    async def _get_user_info(self, user_id: str) -> tuple[str, str]:
        """Return (display_name, avatar_url) for a Slack user, with caching."""
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        if self._web is None:
            return user_id, ""
        try:
            resp = await self._web.users_info(user=user_id)
            u = resp["user"]
            if u is None:
                return user_id, ""
            profile = u.get("profile", {})
            name = (
                profile.get("display_name")
                or u.get("real_name")
                or u.get("name")
                or user_id
            )
            avatar = profile.get("image_192") or profile.get("image_72") or ""
        except Exception:
            name, avatar = user_id, ""
        self._user_cache[user_id] = (name, avatar)
        return name, avatar

    async def _download_file(self, f: dict, max_size: int) -> Attachment | None:
        url = f.get("url_private_download") or f.get("url_private", "")
        mime = f.get("mimetype", "application/octet-stream")
        name = f.get("name") or f.get("title") or "attachment"
        size = f.get("size", -1)

        if not url or (size > 0 and size > self.config.max_file_size):
            return None

        if not self.config.bot_token or self._session is None:
            return None

        try:
            async with self._session.get(
                url, headers={"Authorization": f"Bearer {self.config.bot_token}"}
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
        except Exception as e:
            logger.warning(f"Slack [{self.instance_id}] file download failed: {e}")
            return None

        if len(data) > max_size:
            return None

        return Attachment(
            type=_mime_to_att_type(mime),
            url="",
            name=name,
            size=len(data),
            data=data,
        )

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
        rich_header = kwargs.get("rich_header")
        if rich_header:
            t, c = rich_header.get("title", ""), rich_header.get("content", "")
            prefix = f"[{t}" + (f" · {c}" if c else "") + "]"
            text = f"{prefix}\n{text}" if text else prefix

        if self.config.send_method == "webhook":
            # Incoming Webhooks cannot customize username or icon (silently
            # ignored by Slack). Fall back to bot send whenever the message
            # carries attachments OR a custom identity, provided bot_token is
            # available (requires chat:write.customize scope for identity).
            needs_bot = self._web is not None and (
                attachments
                or kwargs.get("webhook_title")
                or kwargs.get("webhook_avatar")
            )
            if needs_bot:
                return await self._send_bot(channel, text, attachments, **kwargs)
            else:
                return await self._send_webhook(text, attachments)
        else:  # "bot"
            return await self._send_bot(channel, text, attachments, **kwargs)

    async def _send_bot(
        self,
        channel: dict,
        text: str,
        attachments: list[Attachment] | None,
        **kwargs,
    ):
        channel_id = channel.get("channel_id")
        if not channel_id:
            logger.warning(
                f"Slack [{self.instance_id}] send: no channel_id in channel {channel}"
            )
            return None
        if self._web is None:
            logger.warning(f"Slack [{self.instance_id}] send: bot_token not configured")
            return None

        title: str = kwargs.get("webhook_title", "") or "{user} ({user_id}) @ {from}"
        avatar: str = kwargs.get("webhook_avatar", "") or "{user_avatar}"
        has_identity = bool(title or avatar)
        reply_to_id = kwargs.get("reply_to_id")
        first_msg_id = None

        def _post_kwargs(msg_text: str) -> dict:
            """Build chat_postMessage kwargs with optional custom identity."""
            m: dict = {"channel": channel_id, "text": msg_text}
            if title:
                m["username"] = title
            if avatar:
                m["icon_url"] = avatar
            if reply_to_id:
                m["thread_ts"] = str(reply_to_id)
            return m

        if text:
            try:
                resp = await self._web.chat_postMessage(**_post_kwargs(text))
                if resp.get("ok"):
                    mid = resp.get("ts")
                    if not first_msg_id:
                        first_msg_id = str(mid)
            except Exception as e:
                logger.error(f"Slack [{self.instance_id}] chat_postMessage failed: {e}")

        source_proxy = self._source_proxy_from_kwargs(kwargs)

        for att in attachments or []:
            if not att.url and att.data is None:
                continue
            result = await media.fetch_attachment(
                att, self.config.max_file_size, source_proxy
            )
            if not result:
                try:
                    label = att.name or att.url or ""
                    resp = await self._web.chat_postMessage(
                        **_post_kwargs(f"[{att.type.capitalize()}: {label}]")
                    )
                    if resp.get("ok"):
                        mid = resp.get("ts")
                        if not first_msg_id:
                            first_msg_id = str(mid)
                except Exception as e:
                    logger.warning(
                        f"Slack [{self.instance_id}] failed to send attachment label: {e}"
                    )
                continue

            data_bytes, mime = result
            fname = media.filename_for(att.name, mime)
            try:
                if has_identity:
                    # files_upload_v2 doesn't support username/icon_url.
                    # Upload without posting, then share the permalink via
                    # chat_postMessage so the custom identity is applied.
                    file_resp = await self._web.files_upload_v2(
                        filename=fname,
                        content=data_bytes,
                    )
                    permalink = (file_resp.get("file") or {}).get("permalink", "")
                    if permalink:
                        resp = await self._web.chat_postMessage(
                            **_post_kwargs(permalink)
                        )
                        if resp.get("ok"):
                            mid = resp.get("ts")
                            if not first_msg_id:
                                first_msg_id = str(mid)
                    else:
                        # Fallback: post to channel directly (no custom identity)
                        resp = await self._web.files_upload_v2(
                            channel=channel_id,
                            filename=fname,
                            content=data_bytes,
                            thread_ts=reply_to_id,
                        )
                        # v2 returns a list of files or a single file object
                        # It's harder to get the ts of the resulting message here directly if it's multiple
                else:
                    await self._web.files_upload_v2(
                        channel=channel_id,
                        filename=fname,
                        content=data_bytes,
                        thread_ts=reply_to_id,
                    )
            except Exception as e:
                logger.error(f"Slack [{self.instance_id}] file upload failed: {e}")

        return first_msg_id

    async def _send_webhook(
        self,
        text: str,
        attachments: list[Attachment] | None,
    ):
        webhook_url = self.config.incoming_webhook_url
        if not webhook_url:
            logger.warning(
                f"Slack [{self.instance_id}] send: no incoming_webhook_url configured"
            )
            return
        if self._session is None:
            logger.warning(f"Slack [{self.instance_id}] send: driver not started")
            return

        # Incoming webhooks are text-only; append attachment labels inline
        full_text = text or ""
        for att in attachments or []:
            label = att.name or att.url or ""
            full_text += f"\n[{att.type.capitalize()}: {label}]"

        if not full_text.strip():
            return

        payload: dict = {"text": full_text}

        try:
            async with self._session.post(webhook_url, json=payload) as resp:
                if resp.status not in (200, 204):
                    body = await resp.text()
                    logger.error(
                        f"Slack [{self.instance_id}] incoming webhook error "
                        f"HTTP {resp.status}: {body}"
                    )
        except Exception as e:
            logger.error(
                f"Slack [{self.instance_id}] incoming webhook request failed: {e}"
            )


register("slack", SlackConfig, SlackDriver)
