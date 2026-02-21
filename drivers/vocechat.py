# VoceChat driver.
#
# Receive: aiohttp HTTP server acting as the bot's webhook endpoint.
#          VoceChat POSTs a JSON event for each new message; the endpoint
#          also responds to GET (health-check) with 200 so VoceChat can
#          validate the URL.
#
# Send:    POST /api/bot/send_to_group/{gid}  — channel message
#          POST /api/bot/send_to_user/{uid}   — direct message
#          Files are uploaded first via POST /api/bot/file/upload, then
#          referenced with Content-Type: vocechat/file.
#
# Config keys (under vocechat.<instance_id>):
#   server_url    – Base URL of the VoceChat server (required),
#                   e.g. "https://chat.example.com"
#   api_key       – Bot API key shown in the bot settings page (required)
#   listen_port   – HTTP port for the webhook endpoint (default: 8091)
#   listen_path   – HTTP path for the webhook endpoint
#                   (default: "/vocechat/webhook")
#   max_file_size – Max bytes per attachment (default: 50 MB)
#
# Rule channel keys (one of):
#   gid – VoceChat group/channel ID  (integer or string)
#   uid – VoceChat user ID for DMs   (integer or string)

import asyncio
import json

import aiohttp
from aiohttp import web

import services.logger as log
import services.media as media
from services.message import Attachment, NormalizedMessage
from services.config_schema import _DriverConfig
from drivers import BaseDriver


class VoceChatConfig(_DriverConfig):
    server_url:    str
    api_key:       str
    listen_port:   int = 8091
    listen_path:   str = "/vocechat/webhook"
    max_file_size: int = 50 * 1024 * 1024


l = log.get_logger()


def _mime_to_att_type(mime: str) -> str:
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "voice"
    return "file"


class VoceChatDriver(BaseDriver[VoceChatConfig]):

    def __init__(self, instance_id: str, config: VoceChatConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._session:    aiohttp.ClientSession | None = None
        self._user_cache: dict[int, tuple[str, str]]   = {}  # uid → (name, avatar)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self._session = aiohttp.ClientSession(
            headers={"x-api-key": self.config.api_key}
        )
        self.bridge.register_sender(self.instance_id, self.send)

        app = web.Application()
        app.router.add_get(self.config.listen_path,  self._handle_health)
        app.router.add_post(self.config.listen_path, self._handle_event)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.config.listen_port)
        await site.start()
        l.info(
            f"VoceChat [{self.instance_id}] webhook listening on "
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

    @staticmethod
    async def _handle_health(_: web.Request) -> web.Response:
        """Health-check: VoceChat verifies the URL with a GET before saving it."""
        return web.Response(status=200, text="ok")

    async def _handle_event(self, request: web.Request) -> web.Response:
        try:
            body  = await request.read()
            event = json.loads(body)
        except Exception:
            return web.Response(status=400, text="Bad JSON")

        asyncio.create_task(self._dispatch(event))
        return web.Response(status=200, text="ok")

    async def _dispatch(self, event: dict) -> None:
        detail = event.get("detail", {})
        # Only handle normal posts and replies; skip edits, deletes, reactions
        if detail.get("type") not in ("normal", "reply"):
            return

        content_type: str = detail.get("content_type", "")
        content:      str = detail.get("content", "") or ""
        from_uid:     int = event.get("from_uid", 0)
        target:       dict = event.get("target", {})

        # Derive the channel dict from the target
        if "gid" in target:
            channel = {"gid": target["gid"]}
        elif "uid" in target:
            # DM: the target uid is the bot; route replies back to the sender
            channel = {"uid": from_uid}
        else:
            return

        server   = self.config.server_url.rstrip("/")
        max_size = self.config.max_file_size

        text        = ""
        attachments: list[Attachment] = []

        if content_type in ("text/plain", "text/markdown"):
            text = content.strip()
        elif content_type == "vocechat/file":
            att = await self._fetch_file_msg(content, server, max_size)
            if att:
                attachments.append(att)
        else:
            # Unsupported content type — skip silently
            return

        if not text and not attachments:
            return

        display_name, avatar = await self._get_user_info(from_uid, server)

        normalized = NormalizedMessage(
            platform="vocechat",
            instance_id=self.instance_id,
            channel=channel,
            user=display_name,
            user_id=str(from_uid),
            user_avatar=avatar,
            text=text,
            attachments=attachments,
        )
        await self.bridge.on_message(normalized)

    async def _get_user_info(self, uid: int, server: str) -> tuple[str, str]:
        if uid in self._user_cache:
            return self._user_cache[uid]
        if self._session is None:
            return str(uid), ""

        name, avatar = str(uid), ""
        try:
            async with self._session.get(
                f"{server}/api/bot/user/{uid}",
                params={"uid": uid},
            ) as resp:
                if resp.status == 200:
                    u = await resp.json(content_type=None)
                    name   = u.get("name") or str(uid)
                    avatar = f"{server}/api/resource/avatar?uid={uid}"
                else:
                    body = await resp.text()
                    l.warning(
                        f"VoceChat [{self.instance_id}] user lookup for uid={uid} "
                        f"failed HTTP {resp.status}: {body[:200]}"
                    )
        except Exception as e:
            l.warning(
                f"VoceChat [{self.instance_id}] user lookup for uid={uid} error: {e}"
            )

        self._user_cache[uid] = (name, avatar)
        return name, avatar

    async def _fetch_file_msg(
        self, content: str, server: str, max_size: int
    ) -> Attachment | None:
        """Download the file referenced by a vocechat/file message."""
        try:
            ref = json.loads(content)
            path = ref.get("path", "")
        except Exception:
            path = content.strip()

        if not path or self._session is None:
            return None

        url = f"{server}/api/resource/file?path={path}"
        try:
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
                if len(data) > max_size:
                    l.debug(
                        f"VoceChat [{self.instance_id}] file {path!r} "
                        f"exceeds size limit"
                    )
                    return None
                ct   = resp.content_type or "application/octet-stream"
                name = path.rsplit("/", 1)[-1] or "attachment"
                return Attachment(
                    type=_mime_to_att_type(ct),
                    url="",
                    name=name,
                    size=len(data),
                    data=data,
                )
        except Exception as e:
            l.warning(
                f"VoceChat [{self.instance_id}] file download failed: {e}"
            )
            return None

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
            l.warning(f"VoceChat [{self.instance_id}] send: driver not started")
            return

        gid = channel.get("gid")
        uid = channel.get("uid")
        if gid is None and uid is None:
            l.warning(
                f"VoceChat [{self.instance_id}] send: "
                f"no gid or uid in channel {channel}"
            )
            return

        server   = self.config.server_url.rstrip("/")
        max_size = self.config.max_file_size

        endpoint = (
            f"{server}/api/bot/send_to_group/{gid}"
            if gid is not None
            else f"{server}/api/bot/send_to_user/{uid}"
        )

        rich_header = kwargs.get("rich_header")
        if rich_header:
            t, c = rich_header.get("title", ""), rich_header.get("content", "")
            prefix = f"**{t}**" + (f" · *{c}*" if c else "")
            text = f"{prefix}\n{text}" if text else prefix

        if text.strip():
            # Use markdown if rich_header was applied; plain text otherwise
            ct = "text/markdown" if rich_header else "text/plain"
            await self._post_message(endpoint, text.encode(), ct)

        for att in (attachments or []):
            if not att.url and att.data is None:
                continue
            result = await media.fetch_attachment(att, max_size)
            if not result:
                label = att.name or att.url or ""
                await self._post_message(
                    endpoint,
                    f"[{att.type.capitalize()}: {label}]".encode(),
                    "text/plain",
                )
                continue

            data_bytes, mime = result
            fname = media.filename_for(att.name, mime)
            file_path = await self._upload_file(server, data_bytes, fname, mime)
            if file_path:
                body = json.dumps({"path": file_path}).encode()
                await self._post_message(endpoint, body, "vocechat/file")
            else:
                label = att.name or fname
                await self._post_message(
                    endpoint,
                    f"[{att.type.capitalize()}: {label}]".encode(),
                    "text/plain",
                )

    async def _post_message(
        self, url: str, body: bytes, content_type: str
    ) -> None:
        try:
            async with self._session.post(
                url,
                data=body,
                headers={"Content-Type": content_type},
            ) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    l.error(
                        f"VoceChat [{self.instance_id}] send failed "
                        f"HTTP {resp.status}: {text[:200]}"
                    )
        except Exception as e:
            l.error(f"VoceChat [{self.instance_id}] send error: {e}")

    async def _upload_file(
        self,
        server: str,
        data:   bytes,
        fname:  str,
        mime:   str,
    ) -> str | None:
        """Upload a file using VoceChat's two-step API and return its path."""
        if self._session is None:
            return None

        # Step 1: prepare — get a file_id (plain UUID string)
        try:
            async with self._session.post(
                f"{server}/api/bot/file/prepare",
                json={"content_type": mime, "filename": fname},
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    l.error(
                        f"VoceChat [{self.instance_id}] file prepare failed "
                        f"HTTP {resp.status}: {body[:200]}"
                    )
                    return None
                file_id = (await resp.text()).strip().strip('"')
        except Exception as e:
            l.error(f"VoceChat [{self.instance_id}] file prepare error: {e}")
            return None

        # Step 2: upload — multipart with file_id, chunk_data, chunk_is_last
        form = aiohttp.FormData()
        form.add_field("file_id",       file_id)
        form.add_field("chunk_data",    data, filename=fname, content_type=mime)
        form.add_field("chunk_is_last", "true")
        try:
            async with self._session.post(
                f"{server}/api/bot/file/upload", data=form
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    l.error(
                        f"VoceChat [{self.instance_id}] file upload failed "
                        f"HTTP {resp.status}: {body[:200]}"
                    )
                    return None
                js = await resp.json(content_type=None)
                return js.get("path")
        except Exception as e:
            l.error(f"VoceChat [{self.instance_id}] file upload error: {e}")
            return None


from drivers.registry import register
register("vocechat", VoceChatConfig, VoceChatDriver)
