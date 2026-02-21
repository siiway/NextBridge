# Google Chat driver via Google Chat REST API.
#
# Receive: aiohttp HTTP server accepting POST events pushed by Google Chat
#          when a user sends a message to the bot.  Configure the bot's
#          endpoint URL in the Google Cloud Console:
#            APIs & Services → Google Chat API → Configuration →
#            Connection settings → HTTP endpoint URL
#
# Send:    Google Chat REST API using a service-account access token
#          (scope: chat.bot).  Token is cached and refreshed automatically.
#
# Config keys (under googlechat.<instance_id>):
#   service_account_file – Path to service account JSON key file (required*)
#   service_account_json – Inline service account JSON string    (alternative)
#   listen_port          – HTTP port  (default: 8090)
#   listen_path          – HTTP path  (default: "/google-chat/events")
#   endpoint_url         – Full public URL of this endpoint, e.g.
#                          "https://example.com/google-chat/events".
#                          When set, incoming requests are verified against
#                          Google's signed OIDC token.  Safe to omit in
#                          dev / behind a firewall.
#   max_file_size        – Max bytes per attachment (default: 50 MB)
#
# Rule channel keys:
#   space_name – Google Chat space resource name, e.g. "spaces/AAAA"
#
# * Exactly one of service_account_file or service_account_json is required.

import asyncio
import json
from pathlib import Path

import aiohttp
from aiohttp import web
from pydantic import model_validator

import google.oauth2.service_account as _sa
import google.auth.transport.requests as _ga_req

import services.logger as log
import services.media as media
from services.message import Attachment, NormalizedMessage
from services.config_schema import _DriverConfig
from drivers import BaseDriver


class GoogleChatConfig(_DriverConfig):
    service_account_file: str = ""
    service_account_json: str = ""
    listen_port:          int = 8090
    listen_path:          str = "/google-chat/events"
    endpoint_url:         str = ""
    max_file_size:        int = 50 * 1024 * 1024

    @model_validator(mode="after")
    def _require_creds(self) -> "GoogleChatConfig":
        if not self.service_account_file and not self.service_account_json:
            raise ValueError(
                "requires 'service_account_file' or 'service_account_json'"
            )
        return self


l = log.get_logger()

_SCOPES   = ["https://www.googleapis.com/auth/chat.bot"]
_API_BASE = "https://chat.googleapis.com/v1"


def _mime_to_att_type(mime: str) -> str:
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "voice"
    return "file"


class GoogleChatDriver(BaseDriver[GoogleChatConfig]):

    def __init__(self, instance_id: str, config: GoogleChatConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._session:     aiohttp.ClientSession | None = None
        self._creds:       _sa.Credentials | None       = None
        self._token_lock:  asyncio.Lock                 = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        try:
            if self.config.service_account_json:
                sa_info = json.loads(self.config.service_account_json)
            else:
                sa_info = json.loads(
                    Path(self.config.service_account_file).read_text()
                )
            self._creds = _sa.Credentials.from_service_account_info(
                sa_info, scopes=_SCOPES
            )
        except Exception as e:
            l.error(f"Google Chat [{self.instance_id}] credentials load failed: {e}")
            return

        self._session = aiohttp.ClientSession()
        self.bridge.register_sender(self.instance_id, self.send)

        app = web.Application()
        app.router.add_post(self.config.listen_path, self._handle_event)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.config.listen_port)
        await site.start()
        l.info(
            f"Google Chat [{self.instance_id}] listening on "
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
        async with self._token_lock:
            if self._creds is None:
                return ""
            if not self._creds.valid:
                try:
                    await asyncio.to_thread(
                        self._creds.refresh, _ga_req.Request()
                    )
                except Exception as e:
                    l.error(
                        f"Google Chat [{self.instance_id}] token refresh failed: {e}"
                    )
                    return ""
            return self._creds.token or ""

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def _handle_event(self, request: web.Request) -> web.Response:
        if self.config.endpoint_url:
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return web.Response(status=403, text="Missing bearer token")
            if not await self._verify_token(auth[7:]):
                return web.Response(status=403, text="Invalid token")

        try:
            body  = await request.read()
            event = json.loads(body)
        except Exception:
            return web.Response(status=400, text="Bad JSON")

        if event.get("type") != "MESSAGE":
            # Acknowledge other events (ADDED_TO_SPACE, REMOVED_FROM_SPACE…)
            return web.json_response({"text": ""})

        message = event.get("message", {})
        sender  = message.get("sender", {})
        space   = event.get("space", {})

        if sender.get("type") == "BOT":
            return web.json_response({"text": ""})

        # argumentText strips the @mention prefix; fall back to full text
        text:         str = message.get("argumentText") or message.get("text") or ""
        raw_space:    str = space.get("name", "")
        space_name:   str = raw_space if raw_space.startswith("spaces/") else f"spaces/{raw_space}"
        display_name: str = sender.get("displayName") or sender.get("name", "")
        user_id:      str = sender.get("name", "")
        avatar:       str = sender.get("avatarUrl", "")

        max_size: int = self.config.max_file_size
        attachments: list[Attachment] = []
        for att_raw in message.get("attachments", []):
            att = await self._download_attachment(att_raw, max_size)
            if att is not None:
                attachments.append(att)

        if not text.strip() and not attachments:
            return web.json_response({"text": ""})

        normalized = NormalizedMessage(
            platform="googlechat",
            instance_id=self.instance_id,
            channel={"space_name": space_name},
            user=display_name,
            user_id=user_id,
            user_avatar=avatar,
            text=text,
            attachments=attachments,
        )
        asyncio.create_task(self.bridge.on_message(normalized))
        return web.json_response({"text": ""})

    async def _verify_token(self, token: str) -> bool:
        import google.oauth2.id_token as _id_token
        try:
            info = await asyncio.to_thread(
                _id_token.verify_oauth2_token,
                token,
                _ga_req.Request(),
                self.config.endpoint_url,
            )
            return info.get("email") == "chat@system.gserviceaccount.com"
        except Exception as e:
            l.warning(
                f"Google Chat [{self.instance_id}] request verification failed: {e}"
            )
            return False

    async def _download_attachment(
        self, att_raw: dict, max_size: int
    ) -> Attachment | None:
        download_uri = att_raw.get("downloadUri", "")
        ct           = att_raw.get("contentType", "application/octet-stream")
        name         = att_raw.get("contentName", "attachment")
        att_type     = _mime_to_att_type(ct)

        if not download_uri or self._session is None:
            return Attachment(type=att_type, url=download_uri, name=name, size=-1, data=None)

        token   = await self._get_token()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with self._session.get(download_uri, headers=headers) as resp:
                if resp.status != 200:
                    return Attachment(type=att_type, url=download_uri, name=name, size=-1, data=None)
                data = await resp.read()
                if len(data) > max_size:
                    l.debug(
                        f"Google Chat [{self.instance_id}] attachment "
                        f"{name!r} exceeds size limit, skipping data"
                    )
                    return Attachment(type=att_type, url=download_uri, name=name, size=len(data), data=None)
                return Attachment(type=att_type, url="", name=name, size=len(data), data=data)
        except Exception as e:
            l.warning(
                f"Google Chat [{self.instance_id}] attachment download failed: {e}"
            )
            return Attachment(type=att_type, url=download_uri, name=name, size=-1, data=None)

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
            l.warning(f"Google Chat [{self.instance_id}] send: driver not started")
            return

        space_name = channel.get("space_name", "")
        if not space_name:
            l.warning(
                f"Google Chat [{self.instance_id}] send: "
                f"no space_name in channel {channel}"
            )
            return

        # Accept bare ID ("AAQAXiYeDA4X") or full resource name ("spaces/AAQAXiYeDA4X")
        if not space_name.startswith("spaces/"):
            space_name = f"spaces/{space_name}"

        token = await self._get_token()
        if not token:
            l.error(
                f"Google Chat [{self.instance_id}] send: could not obtain access token"
            )
            return

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        }
        api_url  = f"{_API_BASE}/{space_name}/messages"
        max_size = self.config.max_file_size

        rich_header = kwargs.get("rich_header")
        if rich_header:
            t, c = rich_header.get("title", ""), rich_header.get("content", "")
            prefix = f"*{t}*" + (f" · _{c}_" if c else "")
            text = f"{prefix}\n{text}" if text else prefix

        if text.strip():
            await self._post_message(api_url, headers, {"text": text})

        for att in (attachments or []):
            if not att.url and att.data is None:
                continue

            # Images with a public URL → card widget (renders inline, no upload needed)
            if att.type == "image" and att.url:
                await self._post_message(api_url, headers, {
                    "cardsV2": [{
                        "cardId": "img",
                        "card": {
                            "sections": [{
                                "widgets": [{
                                    "image": {
                                        "imageUrl": att.url,
                                        "altText": att.name or "image",
                                    }
                                }]
                            }]
                        },
                    }]
                })
                continue

            # All other attachments (or images with bytes only) → multipart upload
            result = await media.fetch_attachment(att, max_size)
            if not result:
                label = att.name or att.url or ""
                await self._post_message(
                    api_url, headers,
                    {"text": f"[{att.type.capitalize()}: {label}]"},
                )
                continue

            data_bytes, mime = result
            await self._post_media(space_name, headers, data_bytes, mime)

    async def _post_media(
        self,
        space_name: str,
        headers: dict,
        data_bytes: bytes,
        mime: str,
    ) -> None:
        """Upload a file via the Google Chat multipart media upload endpoint."""
        boundary = "gc_nb_boundary"
        meta     = json.dumps({}).encode()
        body = (
            f"--{boundary}\r\nContent-Type: application/json\r\n\r\n".encode()
            + meta
            + f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n"
              f"Content-Transfer-Encoding: binary\r\n\r\n".encode()
            + data_bytes
            + f"\r\n--{boundary}--".encode()
        )
        upload_url = (
            f"https://upload.googleapis.com/upload/v1/{space_name}/messages"
        )
        upload_headers = {
            "Authorization": headers["Authorization"],
            "Content-Type":  f"multipart/related; boundary={boundary}",
        }
        try:
            async with self._session.post(
                upload_url,
                data=body,
                headers=upload_headers,
                params={"uploadType": "multipart"},
            ) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    l.error(
                        f"Google Chat [{self.instance_id}] media upload failed "
                        f"HTTP {resp.status}: {text[:200]}"
                    )
        except Exception as e:
            l.error(f"Google Chat [{self.instance_id}] media upload error: {e}")

    async def _post_message(self, url: str, headers: dict, body: dict) -> None:
        try:
            async with self._session.post(url, json=body, headers=headers) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    l.error(
                        f"Google Chat [{self.instance_id}] post failed "
                        f"HTTP {resp.status}: {text[:200]}"
                    )
        except Exception as e:
            l.error(f"Google Chat [{self.instance_id}] post error: {e}")


from drivers.registry import register
register("googlechat", GoogleChatConfig, GoogleChatDriver)
