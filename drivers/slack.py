# Slack driver.
#
# Receive: two modes —
#   Socket Mode (when app_token is set)              – WebSocket; no public URL needed.
#   Events API  (when signing_secret + listen_port)  – HTTP webhook from Slack.
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
#   listen_port          – HTTP port for Events API receive
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

import aiohttp
from aiohttp import web

from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web.async_client import AsyncWebClient

import services.logger as log
import services.media as media
from services.message import Attachment, NormalizedMessage
from services.config_schema import SlackConfig
from drivers import BaseDriver

l = log.get_logger()

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
    expected = "v0=" + _hmac.new(
        signing_secret.encode(),
        base.encode(),
        hashlib.sha256,
    ).hexdigest()
    return _hmac.compare_digest(expected, signature)


class SlackDriver(BaseDriver[SlackConfig]):

    def __init__(self, instance_id: str, config: SlackConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._web: AsyncWebClient | None = None
        self._sm: SocketModeClient | None = None
        self._session: aiohttp.ClientSession | None = None
        self._user_cache: dict[str, tuple[str, str]] = {}  # user_id → (name, avatar_url)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        bot_token      = self.config.bot_token
        app_token      = self.config.app_token
        send_method    = self.config.send_method
        webhook_url    = self.config.incoming_webhook_url
        signing_secret = self.config.signing_secret
        listen_port    = self.config.listen_port
        listen_path    = self.config.listen_path

        # Register early so the bridge can route to us; individual send helpers
        # guard against uninitialized state.
        self.bridge.register_sender(self.instance_id, self.send)
        self._session = aiohttp.ClientSession()

        if bot_token:
            self._web = AsyncWebClient(token=bot_token)

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
                l.info(f"Slack [{self.instance_id}] Socket Mode connected")
                await asyncio.Event().wait()
            finally:
                await self._sm.close()
                await self._session.close()
            return

        # ------ Events API webhook receive -----------------------------------
        if signing_secret and listen_port:
            web_app = web.Application()
            web_app.router.add_post(listen_path, self._handle_events_api)
            runner = web.AppRunner(web_app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", listen_port)
            await site.start()
            l.info(
                f"Slack [{self.instance_id}] Events API listening on "
                f"0.0.0.0:{listen_port}{listen_path}"
            )
            try:
                await asyncio.Event().wait()
            finally:
                await runner.cleanup()
                await self._session.close()
            return

        # ------ Send-only mode -----------------------------------------------
        if send_method == "webhook" and not webhook_url:
            l.error(
                f"Slack [{self.instance_id}] send_method='webhook' requires incoming_webhook_url"
            )
            return
        if send_method != "webhook" and not bot_token:
            l.error(f"Slack [{self.instance_id}] send_method='bot' requires bot_token")
            return
        l.info(f"Slack [{self.instance_id}] running in send-only mode")
        # Session stays open; task completes and send() continues to work via the bridge.

    # ------------------------------------------------------------------
    # Receive — Socket Mode
    # ------------------------------------------------------------------

    async def _on_request(self, client: SocketModeClient, req: SocketModeRequest) -> None:
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

    async def _handle_events_api(self, request: web.Request) -> web.Response:
        body = await request.read()

        if self.config.signing_secret and not _verify_slack_signature(self.config.signing_secret, request.headers, body):
            return web.Response(status=403, text="Invalid signature")

        try:
            payload = json.loads(body)
        except Exception:
            return web.Response(status=400, text="Bad JSON")

        # URL verification challenge (sent by Slack when the endpoint is first saved)
        if payload.get("type") == "url_verification":
            return web.json_response({"challenge": payload.get("challenge", "")})

        event = payload.get("event", {})
        asyncio.create_task(self._dispatch_event(event))
        return web.Response(status=200, text="ok")

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

        text       = event.get("text", "")
        channel_id = event.get("channel", "")
        user_id    = event.get("user", "")

        if not channel_id or not user_id:
            return

        display_name, user_avatar = await self._get_user_info(user_id)

        max_size: int = self.config.max_file_size
        attachments: list[Attachment] = []
        for f in event.get("files", []):
            att = await self._download_file(f, max_size)
            if att is not None:
                attachments.append(att)

        if not text.strip() and not attachments:
            return

        normalized = NormalizedMessage(
            platform="slack",
            instance_id=self.instance_id,
            channel={"channel_id": channel_id},
            user=display_name,
            user_id=user_id,
            user_avatar=user_avatar,
            text=text,
            attachments=attachments,
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
            profile = u.get("profile", {})
            name = (
                profile.get("display_name")
                or u.get("real_name")
                or u.get("name")
                or user_id
            )
            avatar = (
                profile.get("image_192")
                or profile.get("image_72")
                or ""
            )
        except Exception:
            name, avatar = user_id, ""
        self._user_cache[user_id] = (name, avatar)
        return name, avatar

    async def _download_file(self, f: dict, max_size: int) -> Attachment | None:
        url  = f.get("url_private_download") or f.get("url_private", "")
        mime = f.get("mimetype", "application/octet-stream")
        name = f.get("name") or f.get("title") or "attachment"
        size = f.get("size", -1)

        if not url or (size > 0 and size > max_size):
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
            l.warning(f"Slack [{self.instance_id}] file download failed: {e}")
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
                await self._send_bot(channel, text, attachments, **kwargs)
            else:
                await self._send_webhook(text, attachments)
        else:  # "bot"
            await self._send_bot(channel, text, attachments, **kwargs)

    async def _send_bot(
        self,
        channel: dict,
        text: str,
        attachments: list[Attachment] | None,
        **kwargs,
    ):
        channel_id = channel.get("channel_id")
        if not channel_id:
            l.warning(f"Slack [{self.instance_id}] send: no channel_id in channel {channel}")
            return
        if self._web is None:
            l.warning(f"Slack [{self.instance_id}] send: bot_token not configured")
            return

        max_size: int = self.config.max_file_size
        title: str  = kwargs.get("webhook_title", "") or ""
        avatar: str = kwargs.get("webhook_avatar", "") or ""
        has_identity = bool(title or avatar)

        def _post_kwargs(msg_text: str) -> dict:
            """Build chat_postMessage kwargs with optional custom identity."""
            m: dict = {"channel": channel_id, "text": msg_text}
            if title:
                m["username"] = title
            if avatar:
                m["icon_url"] = avatar
            return m

        if text:
            try:
                await self._web.chat_postMessage(**_post_kwargs(text))
            except Exception as e:
                l.error(f"Slack [{self.instance_id}] chat_postMessage failed: {e}")

        for att in (attachments or []):
            if not att.url and att.data is None:
                continue
            result = await media.fetch_attachment(att, max_size)
            if not result:
                try:
                    label = att.name or att.url or ""
                    await self._web.chat_postMessage(
                        **_post_kwargs(f"[{att.type.capitalize()}: {label}]")
                    )
                except Exception:
                    pass
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
                        await self._web.chat_postMessage(**_post_kwargs(permalink))
                    else:
                        # Fallback: post to channel directly (no custom identity)
                        await self._web.files_upload_v2(
                            channel=channel_id,
                            filename=fname,
                            content=data_bytes,
                        )
                else:
                    await self._web.files_upload_v2(
                        channel=channel_id,
                        filename=fname,
                        content=data_bytes,
                    )
            except Exception as e:
                l.error(f"Slack [{self.instance_id}] file upload failed: {e}")

    async def _send_webhook(
        self,
        text: str,
        attachments: list[Attachment] | None,
    ):
        webhook_url = self.config.incoming_webhook_url
        if not webhook_url:
            l.warning(f"Slack [{self.instance_id}] send: no incoming_webhook_url configured")
            return
        if self._session is None:
            l.warning(f"Slack [{self.instance_id}] send: driver not started")
            return

        # Incoming webhooks are text-only; append attachment labels inline
        full_text = text or ""
        for att in (attachments or []):
            label = att.name or att.url or ""
            full_text += f"\n[{att.type.capitalize()}: {label}]"

        if not full_text.strip():
            return

        payload: dict = {"text": full_text}

        try:
            async with self._session.post(webhook_url, json=payload) as resp:
                if resp.status not in (200, 204):
                    body = await resp.text()
                    l.error(
                        f"Slack [{self.instance_id}] incoming webhook error "
                        f"HTTP {resp.status}: {body}"
                    )
        except Exception as e:
            l.error(f"Slack [{self.instance_id}] incoming webhook request failed: {e}")
