# Yunhu (云湖) driver.
# Receive: webhook HTTP server (aiohttp) — Yunhu POSTs events to our endpoint.
# Send:    HTTP POST to the Yunhu open API (async, no dependency on the
#           sync-only yunhu.Openapi helper class).
#
# Config keys (under yunhu.<instance_id>):
#   token        – Bot token from the Yunhu developer portal (required)
#   webhook_port – Port to listen on for incoming webhooks (default 8765)
#   webhook_path – HTTP path for the webhook endpoint (default "/yunhu-webhook")
#   proxy_host   – Cloudflare Worker base URL for the media proxy.
#                  /pfp?url=  is used for Yunhu CDN avatars (adds Referer).
#                  /media?url= is used for external CDN URLs (e.g. Discord)
#                  that are blocked in China so Yunhu's servers can't reach them.
#
# Rule channel keys:
#   chat_id   – Yunhu chat (group) ID
#   chat_type – "group" or "user" (default "group")

import asyncio
from urllib.parse import quote, urlparse

import aiohttp
from aiohttp import web

import services.logger as log
from services.message import Attachment, NormalizedMessage
from services.config_schema import _DriverConfig
from drivers import BaseDriver


class YunhuConfig(_DriverConfig):
    token:        str = ""
    webhook_port: int = 8765
    webhook_path: str = "/yunhu-webhook"
    proxy_host:   str = ""

l = log.get_logger()

_SEND_URL = "https://chat-go.jwzhd.com/open-apis/v1/bot/send"
_DEFAULT_PORT = 8765
_DEFAULT_PATH = "/yunhu-webhook"

# Yunhu's own CDN — no need to proxy through /media
_YUNHU_CDN_SUFFIXES = (".jwznb.com", ".jwzhd.com")
# External domains to route through /media when proxy_host is configured
_PROXY_MEDIA_SUFFIXES = (".discordapp.com", ".discordapp.net", ".discord.com")


class YunhuDriver(BaseDriver[YunhuConfig]):

    def __init__(self, instance_id: str, config: YunhuConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._token: str = config.token
        self._session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self.bridge.register_sender(self.instance_id, self.send)

        if not self._token:
            l.warning(f"Yunhu [{self.instance_id}] no token configured — send disabled")

        self._session = aiohttp.ClientSession()

        port: int = self.config.webhook_port
        path: str = self.config.webhook_path

        app = web.Application()
        app.router.add_post(path, self._handle_webhook)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        l.info(f"Yunhu [{self.instance_id}] webhook listening on :{port}{path}")

        await asyncio.Event().wait()  # run indefinitely

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _proxy_host(self) -> str:
        return self.config.proxy_host.rstrip("/")

    def _proxy_pfp(self, url: str) -> str:
        """Route a Yunhu CDN URL through /pfp so downstream fetchers get the
        required Referer header injected by the Worker."""
        host = self._proxy_host()
        if not host or not url:
            return url
        return f"{host}/pfp?url={quote(url, safe='')}"

    def _proxy_media(self, url: str) -> str:
        """Rewrite an outgoing attachment URL through the proxy when needed.

        - Yunhu CDN URLs (*.jwznb.com / *.jwzhd.com): pass through unchanged —
          Yunhu's own servers can fetch from their own CDN.
        - Discord CDN URLs: rewrite to /media so Yunhu's servers (in China) can
          reach them through Cloudflare.
        - Unknown domains: pass through unchanged.
        """
        host = self._proxy_host()
        if not host or not url:
            return url
        try:
            hostname = urlparse(url).hostname or ""
        except Exception:
            return url
        if any(hostname == s.lstrip(".") or hostname.endswith(s) for s in _YUNHU_CDN_SUFFIXES):
            return url  # Yunhu's own CDN — no proxy needed on the send side
        if any(hostname == s.lstrip(".") or hostname.endswith(s) for s in _PROXY_MEDIA_SUFFIXES):
            return f"{host}/media?url={quote(url, safe='')}"
        return url  # unknown domain — pass through unchanged

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            event_type: str = data.get("header", {}).get("eventType", "")
            event: dict = data.get("event", {})

            if event_type in ("message.receive.normal", "message.receive.instruction"):
                await self._on_message(event)
        except Exception as e:
            l.error(f"Yunhu [{self.instance_id}] webhook handler error: {e}")

        # Yunhu expects a 200 with code=0 to acknowledge receipt
        return web.json_response({"code": 0})

    async def _on_message(self, event: dict):
        sender: dict = event.get("sender", {})
        message: dict = event.get("message", {})

        chat_id: str = str(message.get("chatId", ""))
        chat_type: str = message.get("chatType", "group")
        user_id: str = str(sender.get("senderId", ""))
        username: str = sender.get("senderNickname", "") or user_id
        raw_avatar: str = sender.get("senderAvatarUrl", "")
        avatar = self._proxy_pfp(raw_avatar)

        content_type: str = message.get("contentType", "")
        content: dict = message.get("content", {})

        text = ""
        attachments: list[Attachment] = []

        if content_type in ("text", "markdown"):
            text = content.get("text", "")
        elif content_type == "image":
            url = self._proxy_pfp(content.get("imageUrl", ""))
            name = content.get("imageName", "image.jpg")
            if url:
                attachments.append(Attachment(type="image", url=url, name=name))
        elif content_type == "video":
            url = self._proxy_pfp(content.get("videoUrl", ""))
            name = content.get("videoName", "video.mp4")
            if url:
                attachments.append(Attachment(type="video", url=url, name=name))
        elif content_type == "file":
            url = self._proxy_pfp(content.get("fileUrl", ""))
            name = content.get("fileName", "file")
            if url:
                attachments.append(Attachment(type="file", url=url, name=name))

        if not text.strip() and not attachments:
            return

        msg = NormalizedMessage(
            platform="yunhu",
            instance_id=self.instance_id,
            channel={"chat_id": chat_id, "chat_type": chat_type},
            user=username,
            user_id=user_id,
            user_avatar=avatar,
            text=text,
            attachments=attachments,
        )
        await self.bridge.on_message(msg)

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
        chat_id = channel.get("chat_id")
        if not chat_id:
            l.warning(f"Yunhu [{self.instance_id}] send: no chat_id in channel {channel}")
            return
        if not self._token:
            l.warning(f"Yunhu [{self.instance_id}] send: no token, message dropped")
            return
        if self._session is None:
            l.warning(f"Yunhu [{self.instance_id}] send: session not ready, message dropped")
            return

        chat_type: str = channel.get("chat_type", "group")

        rich_header = kwargs.get("rich_header")
        if rich_header:
            t, c = rich_header.get("title", ""), rich_header.get("content", "")
            prefix = f"[{t}" + (f" · {c}" if c else "") + "]"
            text = f"{prefix}\n{text}" if text else prefix

        # Build the list of payloads to send: text first, then each attachment
        # as its native Yunhu content type.
        payloads: list[dict] = []

        if text:
            payloads.append({
                "recvId": chat_id,
                "recvType": chat_type,
                "contentType": "text",
                "content": {"text": text},
            })

        for att in (attachments or []):
            if not att.url:
                # No URL to give Yunhu — append a text fallback to the first
                # text payload, or send a standalone text message.
                fallback = f"[{att.type.capitalize()}: {att.name}]" if att.name else None
                if fallback:
                    if payloads and payloads[0]["contentType"] == "text":
                        payloads[0]["content"]["text"] += f"\n{fallback}"
                    else:
                        payloads.append({
                            "recvId": chat_id,
                            "recvType": chat_type,
                            "contentType": "text",
                            "content": {"text": fallback},
                        })
                continue

            url = self._proxy_media(att.url)
            name = att.name or att.url.split("/")[-1]
            if att.type == "image":
                payloads.append({
                    "recvId": chat_id,
                    "recvType": chat_type,
                    "contentType": "image",
                    "content": {"imageUrl": url, "imageName": name},
                })
            elif att.type == "video":
                payloads.append({
                    "recvId": chat_id,
                    "recvType": chat_type,
                    "contentType": "video",
                    "content": {"videoUrl": url, "videoName": name},
                })
            else:  # voice / file / unknown
                payloads.append({
                    "recvId": chat_id,
                    "recvType": chat_type,
                    "contentType": "file",
                    "content": {"fileUrl": url, "fileName": name},
                })

        if not payloads:
            return

        for payload in payloads:
            try:
                async with self._session.post(
                    f"{_SEND_URL}?token={self._token}",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        l.error(
                            f"Yunhu [{self.instance_id}] send failed "
                            f"HTTP {resp.status}: {body}"
                        )
            except Exception as e:
                l.error(f"Yunhu [{self.instance_id}] send failed: {e}")


from drivers.registry import register
register("yunhu", YunhuConfig, YunhuDriver)
