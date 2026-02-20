# Discord driver.
#
# Receive: requires a bot token (bot_token in config).
#          The bot listens for messages via discord.py's gateway.
#          Text content, attachments (images/video/voice/files) are all bridged.
#
# Send:    two modes controlled by "send_method" in config —
#   "webhook" (default) – posts via a Discord webhook URL.
#                          Supports per-message username/avatar via
#                          webhook_title / webhook_avatar in rule msg config.
#                          Attachments are downloaded and re-uploaded as files.
#   "bot"               – sends via the bot itself (requires bot_token).
#
# Config keys (under discord.<instance_id>):
#   bot_token     – Optional. Required for receive and bot-send mode.
#   send_method   – "webhook" (default) | "bot"
#   webhook_url   – Required when send_method == "webhook"
#   max_file_size – Max bytes per attachment when sending (default 8 MB,
#                   Discord webhook limit)

import io
import json
from pathlib import Path
import re

import discord
import aiohttp

import services.logger as log
import services.media as media
from services.message import Attachment, NormalizedMessage
from services.util import get_data_path
from drivers import BaseDriver

l = log.get_logger()

_DEFAULT_MAX = 8 * 1024 * 1024  # 8 MB (Discord webhook limit)

_CQFACE_RE = re.compile(r':cqface(\d+):')


class DiscordDriver(BaseDriver):

    def __init__(self, instance_id: str, config: dict, bridge):
        super().__init__(instance_id, config, bridge)
        self._client: discord.Client | None = None
        self._session: aiohttp.ClientSession | None = None
        self._send_method: str = config.get("send_method", "webhook")
        self._webhook_url: str | None = config.get("webhook_url")
        self._bot_token: str | None = config.get("bot_token")
        # face_id (str) → "<:name:id>" resolved Discord emoji string
        self._emoji_cache: dict[str, str] = {}
        # name → emoji_id index built lazily from discord_emojis.json
        self._emoji_db: dict[str, str] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self.bridge.register_sender(self.instance_id, self.send)
        self._session = aiohttp.ClientSession()

        if not self._bot_token:
            l.warning(
                f"Discord [{self.instance_id}] no bot_token configured — "
                "receive disabled, send-only via webhook"
            )
            return  # Webhook-only: session stays open, send() will be called by bridge

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready():
            l.info(f"Discord [{self.instance_id}] logged in as {self._client.user}")

        @self._client.event
        async def on_message(message: discord.Message):
            if message.author.bot:
                return
            await self._on_message(message)

        # Blocks until the bot disconnects
        await self._client.start(self._bot_token)

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def _on_message(self, message: discord.Message):
        server_id = str(message.guild.id) if message.guild else ""
        channel_id = str(message.channel.id)
        text = message.content

        attachments: list[Attachment] = []
        for att in message.attachments:
            ct = att.content_type or ""
            if ct.startswith("image/"):
                att_type = "image"
            elif ct.startswith("video/"):
                att_type = "video"
            elif ct.startswith("audio/"):
                att_type = "voice"
            else:
                att_type = "file"
            attachments.append(
                Attachment(type=att_type, url=att.url, name=att.filename, size=att.size)
            )

        if not text.strip() and not attachments:
            return

        avatar = (
            str(message.author.display_avatar.url)
            if message.author.display_avatar
            else ""
        )

        msg = NormalizedMessage(
            platform="discord",
            instance_id=self.instance_id,
            channel={"server_id": server_id, "channel_id": channel_id},
            user=message.author.display_name,
            user_id=str(message.author.id),
            user_avatar=avatar,
            text=text,
            attachments=attachments,
        )
        await self.bridge.on_message(msg)

    # ------------------------------------------------------------------
    # CQ face emoji resolution
    # ------------------------------------------------------------------

    def _get_emoji_db(self) -> dict[str, str]:
        """Lazily load and index discord_emojis.json as {emoji_name: emoji_id}.

        Supports two formats:
        - Discord API export: ``{"items": [{"id": "...", "name": "cqface0", ...}]}``
        - Simple map: ``{"0": "emoji_id"}`` or ``{"0": {"name": "...", "id": "..."}}``
        """
        if self._emoji_db is not None:
            return self._emoji_db

        self._emoji_db = {}
        try:
            raw = json.loads(
                (Path(get_data_path()) / "discord_emojis.json").read_text(encoding="utf-8")
            )
            if isinstance(raw, dict) and "items" in raw:
                # Discord API export format
                for item in raw["items"]:
                    name = item.get("name", "")
                    eid  = item.get("id", "")
                    if name and eid:
                        self._emoji_db[name] = eid
            elif isinstance(raw, dict):
                # Simple {face_id: emoji_id | {name, id}} map
                for face_id, entry in raw.items():
                    if isinstance(entry, str):
                        self._emoji_db[f"cqface{face_id}"] = entry
                    elif isinstance(entry, dict):
                        name = entry.get("name", f"cqface{face_id}")
                        eid  = entry.get("id", "")
                        if eid:
                            self._emoji_db[name] = eid
        except FileNotFoundError:
            pass
        except Exception as exc:
            l.warning(f"Discord [{self.instance_id}] failed to read emoji DB: {exc}")

        return self._emoji_db

    def _resolve_cqface(self, face_id: str) -> str:
        """Return the Discord emoji string for a CQ face ID.

        Lookup order:
        1. In-process cache (populated by previous calls).
        2. ``data/discord_emojis.json`` indexed by emoji name ``cqface<id>``.
        3. Walk every guild the bot is connected to and search for a custom
           emoji whose name is ``cqface<id>``.
        4. Fall back to the plain ``:cqface<id>:`` text token.
        """
        if face_id in self._emoji_cache:
            return self._emoji_cache[face_id]

        target_name = f"cqface{face_id}"

        # 1. JSON database
        db = self._get_emoji_db()
        if target_name in db:
            result = f"<:{target_name}:{db[target_name]}>"
            self._emoji_cache[face_id] = result
            return result

        # 2. Discord API — search all guilds the bot has joined
        if self._client is not None:
            for guild in self._client.guilds:
                emoji = discord.utils.get(guild.emojis, name=target_name)
                if emoji is not None:
                    result = str(emoji)  # "<:name:id>"
                    self._emoji_cache[face_id] = result
                    return result

        return f":cqface{face_id}:"  # plain fallback

    def _expand_cqface_emojis(self, text: str) -> str:
        """Replace all ``:cqface<id>:`` tokens with Discord emoji strings."""
        return _CQFACE_RE.sub(lambda m: self._resolve_cqface(m.group(1)), text)

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
        has_cqface = bool(re.search(r':cqface\d+:', text))
        force_bot = (
            has_cqface
            and self.config.get("send_as_bot_when_using_cqface_emoji", False)
            and self._client is not None
        )

        # Resolve the send path first so we know which format override to apply
        is_webhook_send = (
            self._send_method == "webhook"
            and self._webhook_url
            and not force_bot
        )

        # Apply send-path-specific msg_format override if provided
        fmt_key = "webhook_msg_format" if is_webhook_send else "bot_msg_format"
        if fmt_key in kwargs:
            text = kwargs[fmt_key]

        # Expand :cqface<id>: tokens into proper Discord custom emoji strings
        if has_cqface:
            text = self._expand_cqface_emojis(text)

        rich_header = kwargs.get("rich_header")
        if rich_header:
            t, c = rich_header.get("title", ""), rich_header.get("content", "")
            prefix = f"**{t}**" + (f" · *{c}*" if c else "")
            text = f"{prefix}\n{text}" if text else prefix

        if is_webhook_send:
            await self._send_webhook(text, attachments, **kwargs)
        elif self._client is not None:
            await self._send_bot(channel, text, attachments)
        else:
            l.warning(f"Discord [{self.instance_id}] no send method available")

    async def _send_webhook(
        self,
        text: str,
        attachments: list[Attachment] | None,
        **kwargs,
    ):
        if self._session is None or self._webhook_url is None:
            return

        max_size: int = self.config.get("max_file_size", _DEFAULT_MAX)

        payload: dict = {"content": text}
        if title := kwargs.get("webhook_title"):
            payload["username"] = title
        if avatar := kwargs.get("webhook_avatar"):
            payload["avatar_url"] = avatar

        # Download each attachment; collect as (bytes, mime, filename) triples
        files: list[tuple[bytes, str, str]] = []
        for att in (attachments or []):
            if not att.url and att.data is None:
                continue
            result = await media.fetch_attachment(att, max_size)
            if result:
                data_bytes, mime = result
                fname = media.filename_for(att.name, mime)
                files.append((data_bytes, mime, fname))
            else:
                # Size exceeded or download failed — append URL or name as text
                label = att.name or att.url
                ref = f"({att.url})" if att.url else ""
                payload["content"] += f"\n[{att.type.capitalize()}: {label}]{ref}"

        if files:
            form = aiohttp.FormData()
            form.add_field(
                "payload_json", json.dumps(payload), content_type="application/json"
            )
            for i, (data_bytes, mime, fname) in enumerate(files):
                form.add_field(
                    f"files[{i}]", data_bytes, filename=fname, content_type=mime
                )
            async with self._session.post(self._webhook_url, data=form) as resp:
                if resp.status not in (200, 204):
                    body = await resp.text()
                    l.error(
                        f"Discord [{self.instance_id}] webhook error "
                        f"HTTP {resp.status}: {body}"
                    )
        else:
            async with self._session.post(self._webhook_url, json=payload) as resp:
                if resp.status not in (200, 204):
                    body = await resp.text()
                    l.error(
                        f"Discord [{self.instance_id}] webhook error "
                        f"HTTP {resp.status}: {body}"
                    )

    async def _send_bot(
        self,
        channel: dict,
        text: str,
        attachments: list[Attachment] | None,
    ):
        if self._client is None:
            return
        channel_id = channel.get("channel_id")
        if not channel_id:
            l.warning(f"Discord [{self.instance_id}] send_bot: no channel_id")
            return
        ch = self._client.get_channel(int(channel_id))
        if ch is None:
            l.warning(f"Discord [{self.instance_id}] channel {channel_id} not in cache")
            return

        max_size: int = self.config.get("max_file_size", _DEFAULT_MAX)

        discord_files: list[discord.File] = []
        for att in (attachments or []):
            if not att.url and att.data is None:
                continue
            result = await media.fetch_attachment(att, max_size)
            if result:
                data_bytes, mime = result
                fname = media.filename_for(att.name, mime)
                discord_files.append(discord.File(io.BytesIO(data_bytes), filename=fname))
            else:
                label = att.name or att.url
                ref = f"({att.url})" if att.url else ""
                text += f"\n[{att.type.capitalize()}: {label}]{ref}"

        await ch.send(text or None, files=discord_files)
