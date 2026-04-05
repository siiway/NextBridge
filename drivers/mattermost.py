# Mattermost driver.
#
# Receive: WebSocket connection to /api/v4/websocket.
#          Authenticated via a token challenge immediately after connect.
#          Streams "posted" events for incoming messages; file attachments
#          are downloaded eagerly using the same token.
#
# Send:    POST /api/v4/posts.  Attachments are uploaded to /api/v4/files
#          first, then referenced in the post via file_ids.
#
# Config keys (under mattermost.<instance_id>):
#   server_url    – Base URL of the Mattermost server (required),
#                   e.g. "https://mattermost.example.com"
#   token         – Bot token or personal access token (required)
#   max_file_size – Max bytes per attachment (default 50 MB)
#
# Rule channel keys:
#   channel_id – Mattermost channel ID

from drivers.registry import register
import asyncio
import json

import aiohttp
from aiohttp_socks import ProxyConnector

import services.logger as log
import services.media as media
from services.message import Attachment, NormalizedMessage
from services.config_schema import _DriverConfig
from services.config import get_proxy, UNSET
from drivers import BaseDriver


class MattermostConfig(_DriverConfig):
    server_url: str
    token: str
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


class MattermostDriver(BaseDriver[MattermostConfig]):
    def __init__(self, instance_id: str, config: MattermostConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._session: aiohttp.ClientSession | None = None
        self._bot_user_id: str = ""
        self._user_cache: dict[str, tuple[str, str]] = {}
        self._username_cache: dict[str, str] = {}
        self._proxy = get_proxy(config.proxy)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        server = self.config.server_url.rstrip("/")
        token = self.config.token

        if self._proxy:
            connector = ProxyConnector.from_url(self._proxy, rdns=True)
            logger.info(f"Mattermost [{self.instance_id}] use proxy {self._proxy}")
        else:
            connector = aiohttp.TCPConnector(ssl=True)

        self._session = aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {token}"}, connector=connector
        )

        # Resolve the bot's own user_id so we can ignore echo messages
        try:
            async with self._session.get(f"{server}/api/v4/users/me") as resp:
                if resp.status == 200:
                    me = await resp.json()
                    self._bot_user_id = me.get("id", "")
                    logger.info(
                        f"Mattermost [{self.instance_id}] logged in as "
                        f"{me.get('username', '?')} ({self._bot_user_id})"
                    )
                else:
                    logger.error(
                        f"Mattermost [{self.instance_id}] /users/me failed "
                        f"HTTP {resp.status}"
                    )
        except Exception as e:
            logger.error(f"Mattermost [{self.instance_id}] /users/me error: {e}")

        self.bridge.register_sender(self.instance_id, self.send)

        ws_url = (
            server.replace("https://", "wss://").replace("http://", "ws://")
        ) + "/api/v4/websocket"
        logger.info(f"Mattermost [{self.instance_id}] connecting to {ws_url}")

        try:
            while True:
                try:
                    async with self._session.ws_connect(ws_url) as ws:
                        await ws.send_json(
                            {
                                "seq": 1,
                                "action": "authentication_challenge",
                                "data": {"token": token},
                            }
                        )
                        logger.info(f"Mattermost [{self.instance_id}] connected")
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    await self._on_event(json.loads(msg.data), server)
                                except Exception:
                                    logger.exception(
                                        f"Mattermost [{self.instance_id}] handler error"
                                    )
                            elif msg.type in (
                                aiohttp.WSMsgType.CLOSE,
                                aiohttp.WSMsgType.ERROR,
                                aiohttp.WSMsgType.CLOSED,
                            ):
                                break
                except aiohttp.ClientError:
                    logger.exception(
                        f"Mattermost [{self.instance_id}] connection error"
                    )

                logger.info(f"Mattermost [{self.instance_id}] reconnecting in 5 s...")
                await asyncio.sleep(5)
        finally:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def _on_event(self, data: dict, server: str) -> None:
        if data.get("event") != "posted":
            return

        # data.post is a double-encoded JSON string
        try:
            post = json.loads(data.get("data", {}).get("post", "{}"))
        except Exception:
            return

        user_id = post.get("user_id", "")
        channel_id = post.get("channel_id", "")
        text = post.get("message", "")
        file_ids = post.get("file_ids") or []

        if not channel_id or not user_id:
            return
        if user_id == self._bot_user_id:
            return
        # Skip system posts (joins, leaves, header changes, etc.)
        if post.get("type"):
            return

        mentions = []
        raw_mentions = data.get("mentions")
        if raw_mentions:
            try:
                mentioned_uids = json.loads(raw_mentions)
                for uid in mentioned_uids:
                    # Resolve name
                    name, _ = await self._get_user_info(uid, server)
                    mentions.append({"id": uid, "name": name})
            except Exception:
                pass

        display_name, avatar_url = await self._get_user_info(user_id, server)
        username = await self._get_username(user_id, server)

        attachments: list[Attachment] = []
        for file_id in file_ids:
            att = await self._download_file(file_id, server, self.config.max_file_size)
            if att is not None:
                attachments.append(att)

        if not text.strip() and not attachments:
            return

        normalized = NormalizedMessage(
            platform="mattermost",
            instance_id=self.instance_id,
            channel={"channel_id": channel_id},
            nickname=display_name,
            user_id=user_id,
            user_avatar=avatar_url,
            text=text,
            attachments=attachments,
            mentions=mentions,
            source_proxy=self._media_proxy,
            username=username,
        )
        await self.bridge.on_message(normalized)

    async def _get_username(self, user_id: str, server: str) -> str:
        if user_id in self._username_cache:
            return self._username_cache[user_id]
        if self._session is None:
            return ""

        username = ""
        try:
            async with self._session.get(f"{server}/api/v4/users/{user_id}") as resp:
                if resp.status == 200:
                    u = await resp.json()
                    username = u.get("username", "")
        except Exception:
            pass

        if username:
            self._username_cache[user_id] = username
        return username

    async def _get_user_info(self, user_id: str, server: str) -> tuple[str, str]:
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        if self._session is None:
            return user_id, ""

        name, avatar = user_id, ""
        try:
            async with self._session.get(f"{server}/api/v4/users/{user_id}") as resp:
                if resp.status == 200:
                    u = await resp.json()
                    full = (
                        f"{u.get('first_name', '')} {u.get('last_name', '')}"
                    ).strip()
                    name = u.get("nickname") or full or u.get("username", user_id)
                    avatar = f"{server}/api/v4/users/{user_id}/image"
        except Exception:
            pass

        self._user_cache[user_id] = (name, avatar)
        return name, avatar

    async def _download_file(
        self, file_id: str, server: str, max_size: int
    ) -> Attachment | None:
        if self._session is None:
            return None

        ct, name, size = "application/octet-stream", "attachment", -1
        try:
            async with self._session.get(
                f"{server}/api/v4/files/{file_id}/info"
            ) as resp:
                if resp.status == 200:
                    info = await resp.json()
                    ct = info.get("mime_type", ct)
                    name = info.get("name", name)
                    size = info.get("size", -1)
        except Exception:
            pass

        if size > 0 and size > max_size:
            return None

        att_type = _mime_to_att_type(ct)
        try:
            async with self._session.get(f"{server}/api/v4/files/{file_id}") as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
                if len(data) > max_size:
                    return None
                return Attachment(
                    type=att_type, url="", name=name, size=len(data), data=data
                )
        except Exception as e:
            logger.warning(
                f"Mattermost [{self.instance_id}] file {file_id} download failed: {e}"
            )
            return None

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
        reply_to_id = kwargs.get("reply_to_id")

        if self._session is None:
            logger.warning(f"Mattermost [{self.instance_id}] send: driver not started")
            return

        channel_id = channel.get("channel_id", "")
        if not channel_id:
            logger.warning(
                f"Mattermost [{self.instance_id}] send: "
                f"no channel_id in channel {channel}"
            )
            return

        server = self.config.server_url.rstrip("/")

        rich_header = kwargs.get("rich_header")
        if rich_header:
            t, c = rich_header.get("title", ""), rich_header.get("content", "")
            prefix = f"**{t}**" + (f" · *{c}*" if c else "")
            text = f"{prefix}\n{text}" if text else prefix

        # Handle mentions: replace @Name with @username
        mentions = kwargs.get("mentions", [])
        for m in mentions:
            username = await self._get_username(m["id"], server)
            if username:
                text = text.replace(f"@{m['name']}", f"@{username}")

        file_ids: list[str] = []
        text_labels: list[str] = []
        source_proxy = self._source_proxy_from_kwargs(kwargs)

        for att in attachments or []:
            if not att.url and att.data is None:
                continue
            result = await media.fetch_attachment(
                att, self.config.max_file_size, source_proxy
            )
            if not result:
                label = att.name or att.url or ""
                text_labels.append(f"[{att.type.capitalize()}: {label}]")
                continue

            data_bytes, mime = result
            fname = media.filename_for(att.name, mime)
            file_id = await self._upload_file(
                server, channel_id, data_bytes, fname, mime
            )
            if file_id:
                file_ids.append(file_id)
            else:
                label = att.name or fname
                text_labels.append(f"[{att.type.capitalize()}: {label}]")

        full_text = text
        if text_labels:
            full_text = (full_text + "\n" + "\n".join(text_labels)).strip()

        if not full_text.strip() and not file_ids:
            return

        payload: dict = {"channel_id": channel_id, "message": full_text}
        if reply_to_id:
            payload["root_id"] = reply_to_id
        if file_ids:
            payload["file_ids"] = file_ids

        try:
            async with self._session.post(
                f"{server}/api/v4/posts", json=payload
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    logger.error(
                        f"Mattermost [{self.instance_id}] post failed "
                        f"HTTP {resp.status}: {body[:200]}"
                    )
        except Exception as e:
            logger.error(f"Mattermost [{self.instance_id}] post error: {e}")

    async def _upload_file(
        self,
        server: str,
        channel_id: str,
        data: bytes,
        fname: str,
        mime: str,
    ) -> str | None:
        if self._session is None:
            return None
        form = aiohttp.FormData()
        form.add_field("channel_id", channel_id)
        form.add_field("files", data, filename=fname, content_type=mime)
        try:
            async with self._session.post(f"{server}/api/v4/files", data=form) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    logger.error(
                        f"Mattermost [{self.instance_id}] file upload failed "
                        f"HTTP {resp.status}: {body[:200]}"
                    )
                    return None
                js = await resp.json()
                infos = js.get("file_infos", [])
                if infos:
                    return infos[0].get("id")
        except Exception as e:
            logger.error(f"Mattermost [{self.instance_id}] file upload error: {e}")
        return None


register("mattermost", MattermostConfig, MattermostDriver)
