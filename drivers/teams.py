# Microsoft Teams driver via Bot Framework.
#
# Receive: aiohttp HTTP server that accepts POST requests from the Bot
#          Framework connector.  Point your Azure bot's messaging endpoint at
#          http(s)://<host>:<listen_port><listen_path>.
#
# Send:    Bot Connector REST API.  An OAuth2 client-credentials token is
#          obtained from Microsoft identity and cached until it expires.
#
# Config keys (under teams.<instance_id>):
#   app_id        – Azure bot application (client) ID     (required)
#   app_secret    – Azure bot client secret               (required)
#   listen_port   – HTTP port for the messaging endpoint  (default: 3978)
#   listen_path   – HTTP path for the messaging endpoint  (default: "/api/messages")
#   max_file_size – Max bytes per attachment when sending (default 20 MB)
#
# Rule channel keys:
#   service_url     – Value of the "serviceUrl" field in incoming activities
#                     (e.g. "https://smba.trafficmanager.net/amer/")
#   conversation_id – Value of activity.conversation.id

import asyncio
import json
import time

import aiohttp
from aiohttp import web

import services.logger as log
import services.media as media
from services.message import Attachment, NormalizedMessage
from services.config_schema import _DriverConfig
from drivers import BaseDriver


class TeamsConfig(_DriverConfig):
    app_id:        str
    app_secret:    str
    listen_port:   int = 3978
    listen_path:   str = "/api/messages"
    max_file_size: int = 20 * 1024 * 1024


l = log.get_logger()

_TOKEN_URL = (
    "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
)
_SCOPE = "https://api.botframework.com/.default"


class TeamsDriver(BaseDriver[TeamsConfig]):

    def __init__(self, instance_id: str, config: TeamsConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._session: aiohttp.ClientSession | None = None
        self._access_token: str = ""
        self._token_expires: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self._session = aiohttp.ClientSession()
        self.bridge.register_sender(self.instance_id, self.send)

        app = web.Application()
        app.router.add_post(self.config.listen_path, self._handle_activity)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.config.listen_port)
        await site.start()
        l.info(
            f"Teams [{self.instance_id}] listening on "
            f"0.0.0.0:{self.config.listen_port}{self.config.listen_path}"
        )
        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _get_token(self) -> str:
        if self._access_token and time.time() < self._token_expires - 60:
            return self._access_token
        if self._session is None:
            return ""
        data = {
            "grant_type":    "client_credentials",
            "client_id":     self.config.app_id,
            "client_secret": self.config.app_secret,
            "scope":         _SCOPE,
        }
        try:
            async with self._session.post(_TOKEN_URL, data=data) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    l.error(
                        f"Teams [{self.instance_id}] token fetch failed "
                        f"HTTP {resp.status}: {body}"
                    )
                    return ""
                js = await resp.json()
                self._access_token = js.get("access_token", "")
                self._token_expires = time.time() + js.get("expires_in", 3600)
                return self._access_token
        except Exception as e:
            l.error(f"Teams [{self.instance_id}] token fetch error: {e}")
            return ""

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def _handle_activity(self, request: web.Request) -> web.Response:
        try:
            body = await request.read()
            activity = json.loads(body)
        except Exception:
            return web.Response(status=400, text="Bad JSON")

        if activity.get("type") != "message":
            return web.Response(status=200, text="ok")
        if activity.get("channelId") != "msteams":
            return web.Response(status=200, text="ok")

        # Skip messages sent by the bot itself (from.id starts with "28:")
        from_id: str = (activity.get("from") or {}).get("id", "")
        if from_id.startswith("28:"):
            return web.Response(status=200, text="ok")

        text: str = activity.get("text") or ""
        # Strip @-mention of the bot from text (Teams prepends it)
        entities = activity.get("entities") or []
        for ent in entities:
            if ent.get("type") == "mention":
                mention_text = (ent.get("mentioned") or {}).get("id", "")
                # Remove <at>BotName</at> patterns from text
                mention_tag = ent.get("text", "")
                if mention_tag and mention_text.startswith("28:"):
                    text = text.replace(mention_tag, "").strip()

        # Attachments (files shared in Teams appear as contentType file/*)
        max_size: int = self.config.max_file_size
        attachments: list[Attachment] = []
        for att_raw in (activity.get("attachments") or []):
            ct = att_raw.get("contentType", "")
            if ct in ("application/vnd.microsoft.card.adaptive",
                       "application/vnd.microsoft.card.thumbnail",
                       "application/vnd.microsoft.card.hero"):
                # Card attachments — skip, already reflected in text
                continue
            url = att_raw.get("contentUrl", "")
            name = att_raw.get("name", "attachment")
            att_type = "file"
            if ct.startswith("image/"):
                att_type = "image"
            elif ct.startswith("video/"):
                att_type = "video"
            elif ct.startswith("audio/"):
                att_type = "voice"
            attachments.append(
                Attachment(type=att_type, url=url, name=name, size=-1, data=None)
            )

        if not text.strip() and not attachments:
            return web.Response(status=200, text="ok")

        from_name: str = (activity.get("from") or {}).get("name", from_id)
        service_url: str = activity.get("serviceUrl", "").rstrip("/")
        conv_id: str = (activity.get("conversation") or {}).get("id", "")

        normalized = NormalizedMessage(
            platform="teams",
            instance_id=self.instance_id,
            channel={"service_url": service_url, "conversation_id": conv_id},
            user=from_name,
            user_id=from_id,
            user_avatar="",
            text=text,
            attachments=attachments,
        )
        asyncio.create_task(self.bridge.on_message(normalized))
        return web.Response(status=200, text="ok")

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
        if self._session is None:
            l.warning(f"Teams [{self.instance_id}] send: driver not started")
            return

        service_url     = channel.get("service_url", "").rstrip("/")
        conversation_id = channel.get("conversation_id", "")
        if not service_url or not conversation_id:
            l.warning(
                f"Teams [{self.instance_id}] send: missing service_url or "
                f"conversation_id in channel {channel}"
            )
            return

        token = await self._get_token()
        if not token:
            l.error(f"Teams [{self.instance_id}] send: could not obtain access token")
            return

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        }

        rich_header = kwargs.get("rich_header")
        if rich_header:
            t, c = rich_header.get("title", ""), rich_header.get("content", "")
            prefix = f"**{t}**" + (f" · *{c}*" if c else "")
            text = f"{prefix}\n{text}" if text else prefix

        url = f"{service_url}/v3/conversations/{conversation_id}/activities"
        max_size: int = self.config.max_file_size

        # Send text first
        if text.strip():
            await self._post_activity(url, headers, {
                "type": "message",
                "text": text,
            })

        # Send attachments
        for att in (attachments or []):
            if not att.url and att.data is None:
                continue
            result = await media.fetch_attachment(att, max_size)
            if not result:
                label = att.name or att.url or ""
                await self._post_activity(url, headers, {
                    "type": "message",
                    "text": f"[{att.type.capitalize()}: {label}]",
                })
                continue

            data_bytes, mime = result
            fname = media.filename_for(att.name, mime)

            if mime.startswith("image/"):
                import base64 as _b64
                b64 = _b64.b64encode(data_bytes).decode()
                card = {
                    "type": "AdaptiveCard",
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "version": "1.3",
                    "body": [{
                        "type": "Image",
                        "url": f"data:{mime};base64,{b64}",
                        "altText": fname,
                    }],
                }
                await self._post_activity(url, headers, {
                    "type": "message",
                    "attachments": [{
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "content": card,
                    }],
                })
            else:
                # Non-image: post a text label (Teams files require SharePoint)
                label = att.name or att.url or fname
                await self._post_activity(url, headers, {
                    "type": "message",
                    "text": f"[{att.type.capitalize()}: {label}]",
                })

    async def _post_activity(self, url: str, headers: dict, body: dict) -> None:
        try:
            async with self._session.post(url, json=body, headers=headers) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    l.error(
                        f"Teams [{self.instance_id}] post activity failed "
                        f"HTTP {resp.status}: {text[:200]}"
                    )
        except Exception as e:
            l.error(f"Teams [{self.instance_id}] post activity error: {e}")


from drivers.registry import register
register("teams", TeamsConfig, TeamsDriver)
