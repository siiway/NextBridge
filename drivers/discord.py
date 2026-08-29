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
#   max_file_size – Max bytes per attachment when sending (default 8 MB, Discord webhook limit)
#   send_replies_as_bot – If true, reply messages are sent by bot when available.
#
# Note: webhook_url should be configured per channel in rules, not at instance level.

from drivers.registry import register
import asyncio
import io
import json
from pathlib import Path
import re
from html import unescape
from urllib.parse import urlparse

import discord
import aiohttp

from typing import Literal

from pydantic import field_validator

import services.cqface as cqface
import services.media as media
from services.message import Attachment, NormalizedMessage
from services.message_format import apply_rich_header, parse_richheader_tag
from services.util import get_data_path, mask_url_credentials
from services.config_schema import _DriverConfig, CoercedBool
from services.config import get_proxy, get as get_config, UNSET
from drivers import BaseDriver


class DiscordConfig(_DriverConfig):
    send_method: Literal["webhook", "bot"] = "webhook"
    bot_token: str = ""
    max_file_size: int = 8 * 1024 * 1024
    cqface_webhook_fallback: Literal["bot", "unicode"] = "unicode"
    send_replies_as_bot: CoercedBool = True
    allow_mentions_everyone: CoercedBool = False
    allow_mentions_users: CoercedBool = True
    allow_mentions_roles: CoercedBool = False
    sanitize_mass_mentions: CoercedBool = True
    enable_recall: CoercedBool = True
    auto_link_image_hosts: list[str] = ["discordmedia.com", "tenor.com"]
    auto_link_image_show_original_url: CoercedBool = True
    proxy: str | None = UNSET

    @field_validator("cqface_webhook_fallback", mode="before")
    def _normalize_cqface_webhook_fallback(cls, value):
        if isinstance(value, bool):
            return "bot" if value else "unicode"
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in ("bot", "unicode"):
                return normalized
        return value

    @field_validator("auto_link_image_hosts", mode="before")
    def _normalize_auto_link_image_hosts(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",")]
        if isinstance(value, list):
            return [str(item).strip().lower() for item in value if str(item).strip()]
        return value


_CQFACE_RE = re.compile(r":cqface(\d+):")
_DISCORD_EMOJI_RE = re.compile(r"<a?:(\w+):(\d+)>")
_MASS_MENTION_RE = re.compile(r"@(everyone|here)\b", re.IGNORECASE)
_SINGLE_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
_META_IMAGE_RE = re.compile(
    r'<meta\s+[^>]*(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]*\bcontent=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_META_IMAGE_REVERSE = re.compile(
    r'<meta\s+[^>]*\bcontent=["\']([^"\']+)["\'][^>]*(?:property|name)=["\'](?:og:image|twitter:image)["\']',
    re.IGNORECASE,
)


def _sanitize_mass_mentions(text: str) -> tuple[str, bool]:
    """Neutralize @everyone/@here so they cannot trigger mass pings."""
    sanitized, count = _MASS_MENTION_RE.subn(lambda m: f"@ {m.group(1)}", text)
    return sanitized, count > 0


def _extract_custom_emojis(text: str) -> tuple[str, list[Attachment]]:
    attachments = []

    def _replace_emoji(m: re.Match) -> str:
        name = m.group(1)
        eid = m.group(2)
        ext = "gif" if m.group(0).startswith("<a") else "png"
        url = f"https://cdn.discordapp.com/emojis/{eid}.{ext}"
        attachments.append(Attachment(type="image", url=url, name=f"{name}.{ext}"))
        return ""

    cleaned = _DISCORD_EMOJI_RE.sub(_replace_emoji, text)
    return cleaned, attachments


def _host_matches(host: str, allowed_hosts: list[str]) -> bool:
    host = host.lower().strip(".")
    for allowed in allowed_hosts:
        allowed = allowed.lower().strip(".")
        if host == allowed or host.endswith(f".{allowed}"):
            return True
    return False


class DiscordDriver(BaseDriver[DiscordConfig]):
    def __init__(self, instance_id: str, config: DiscordConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self.config = config
        self._client: discord.Client | None = None
        self._session: aiohttp.ClientSession | None = None
        self._send_method: str = config.send_method
        self._bot_token: str | None = config.bot_token or None
        self._proxy = get_proxy(config.proxy)
        # face_id (str) → "<:name:id>" resolved Discord emoji string
        self._emoji_cache: dict[str, str] = {}
        # Message IDs we deleted ourselves (bridged recalls). Used to ignore the
        # raw delete event Discord dispatches back so we don't loop.
        self._recall_suppress: set[str] = set()
        # Message IDs we pinned ourselves (bridged pins). Used to ignore the
        # MESSAGE_UPDATE event Discord dispatches back so we don't loop.
        self._pin_suppress: set[str] = set()
        # name → emoji_id index built lazily from discord_emojis.json
        self._emoji_db: dict[str, str] | None = None
        self._stopping = False
        # Ordered FIFO queue + single worker: Discord dispatches each event in a
        # detached task, so without serialization bridged messages can be
        # reordered on the target platform.
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._message_worker_task: asyncio.Task | None = None

    @staticmethod
    def _bounded_add(s: set[str], item: str, maxlen: int = 10000) -> None:
        """Add *item* to a suppression set, clearing it when it grows too large."""
        if len(s) >= maxlen:
            s.clear()
        s.add(item)

    def _allowed_mentions_parse(self) -> list[str]:
        parse: list[str] = []
        if self.config.allow_mentions_everyone:
            parse.append("everyone")
        if self.config.allow_mentions_users:
            parse.append("users")
        if self.config.allow_mentions_roles:
            parse.append("roles")
        return parse

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self.bridge.register_sender(self.instance_id, self.send)
        self.bridge.register_editor(self.instance_id, self.edit)
        if self.config.enable_recall:
            self.bridge.register_deleter(self.instance_id, self.delete)
        self.bridge.register_pinner(self.instance_id, self.pin)
        self.bridge.register_unpinner(self.instance_id, self.unpin)

        ssl_verify = get_config("global.ssl_verify", True)
        if ssl_verify is None:
            ssl_verify = True
        connector = None
        if not ssl_verify or self._proxy:
            connector = aiohttp.TCPConnector(ssl=False)

        if self._proxy:
            self.logger.debug(f"using proxy {mask_url_credentials(self._proxy)}")
            self._session = aiohttp.ClientSession(
                connector=connector, proxy=self._proxy
            )
        else:
            self._session = aiohttp.ClientSession(connector=connector)

        if not self._bot_token:
            self.logger.warning(
                "no bot_token configured — receive disabled, send-only via webhook"
            )
            return  # Webhook-only: session stays open, send() will be called by bridge

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(
            intents=intents, connector=connector, proxy=self._proxy
        )

        @self._client.event
        async def on_ready():
            if self._client is None:
                self.logger.warning(
                    f"Discord [{self.instance_id}] on_ready: client not started"
                )
                return
            self.logger.debug(f"logged in as {self._client.user}")

        @self._client.event
        async def on_message(message: discord.Message):
            if message.author.bot:
                return
            self._message_queue.put_nowait(message)

        @self._client.event
        async def on_message_edit(before: discord.Message, after: discord.Message):
            # Detect pin/unpin events. `before` is None when the message is
            # not in the internal cache; `after` may be partial but still
            # carries the `pinned` field for pin/unpin updates.
            try:
                is_pin_change = (
                    before is not None and before.pinned != after.pinned
                ) or (before is None and after.pinned is not None)
            except (AttributeError, ValueError):
                is_pin_change = False
            if is_pin_change:
                await self._on_message_pin(after, after.pinned)
                return
            # Skip bot messages for edit detection
            try:
                if after.author.bot:
                    return
            except (AttributeError, ValueError):
                return
            # Discord fires MESSAGE_UPDATE for reasons other than a real content
            # edit, e.g. a message being pinned/unpinned or an embed/preview
            # being auto-generated for a link. In those cases the actual text is
            # unchanged, so treating them as edits would spuriously mark the
            # bridged message as "edited" on other platforms. Only bridge the
            # edit when the visible content actually changed.
            if before is not None and not self._is_content_edit(before, after):
                return
            await self._on_message_edit(after)

        @self._client.event
        async def on_raw_message_delete(
            payload: discord.RawMessageDeleteEvent,
        ):
            await self._on_raw_message_delete(payload)

        if self._message_worker_task is None or self._message_worker_task.done():
            self._message_worker_task = asyncio.create_task(self._message_worker())

        # Blocks until the bot disconnects. Reconnect on unexpected disconnect
        # (token failure, kick, network drop) with exponential backoff.
        attempt = 0
        while not self._stopping:
            try:
                await self._client.start(self._bot_token)
            except Exception:
                if self._stopping:
                    break
                self.logger.exception(
                    f"Discord [{self.instance_id}] client disconnected unexpectedly"
                )
            if self._stopping:
                break
            attempt += 1
            delay = min(30.0, 2.0 * (2 ** (attempt - 1)))
            self.logger.warning(
                f"Discord [{self.instance_id}] reconnecting in {delay:.0f}s"
            )
            await asyncio.sleep(delay)

    async def stop(self):
        self._stopping = True
        if self._client and not self._client.is_closed():
            await self._client.close()
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def _message_worker(self) -> None:
        while True:
            message = await self._message_queue.get()
            try:
                await self._on_message(message)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger.error(f"message handler error: {e}")
            finally:
                self._message_queue.task_done()

    async def _on_message(self, message: discord.Message):
        server_id = str(message.guild.id) if message.guild else ""
        channel_id = str(message.channel.id)
        self.logger.debug(
            f"message from {message.author} server={server_id} channel={channel_id}"
        )
        # Use clean_content to get mentions as @Name instead of <@id>
        text = message.clean_content

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

        is_forward = False
        if (
            message.reference
            and message.reference.type == discord.MessageReferenceType.forward
        ):
            is_forward = True
            resolved = message.reference.resolved
            if resolved is None and message.reference.message_id is not None:
                try:
                    ref_channel_id = message.reference.channel_id
                    if ref_channel_id and message.guild:
                        ch = message.guild.get_channel(ref_channel_id)
                        if ch is None:
                            ch = await message.guild.fetch_channel(ref_channel_id)
                        if isinstance(
                            ch,
                            (discord.TextChannel, discord.Thread, discord.VoiceChannel),
                        ):
                            resolved = await ch.fetch_message(
                                message.reference.message_id
                            )
                except Exception as e:
                    self.logger.debug(f"failed to fetch forwarded message: {e}")
            if resolved is not None and not isinstance(
                resolved, discord.DeletedReferencedMessage
            ):
                fwd_text = resolved.clean_content
                fwd_author = resolved.author.display_name

                forward_block = (
                    f"转发消息 | From @{fwd_author}:\n{fwd_text}"
                    if fwd_text
                    else f"转发消息 | From @{fwd_author}"
                )
                text = (text + "\n" + forward_block) if text.strip() else forward_block

                for att in resolved.attachments:
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
                        Attachment(
                            type=att_type,
                            url=att.url,
                            name=att.filename,
                            size=att.size,
                        )
                    )

                for sticker in resolved.stickers:
                    if sticker.format in (
                        discord.StickerFormatType.png,
                        discord.StickerFormatType.apng,
                        discord.StickerFormatType.gif,
                    ):
                        ext = (
                            "gif"
                            if sticker.format == discord.StickerFormatType.gif
                            else "png"
                        )
                        attachments.append(
                            Attachment(
                                type="image",
                                url=sticker.url,
                                name=f"{sticker.name}.{ext}",
                            )
                        )
                    elif sticker.format == discord.StickerFormatType.lottie:
                        label = sticker.name
                        if text.strip():
                            text += f"\n[Forwarded Sticker: {label}]"
                        else:
                            text = f"[Forwarded Sticker: {label}]"
            else:
                forward_block = "转发消息 | (原消息已被删除)"
                text = (text + "\n" + forward_block) if text.strip() else forward_block

        for sticker in message.stickers:
            if sticker.format in (
                discord.StickerFormatType.png,
                discord.StickerFormatType.apng,
            ):
                attachments.append(
                    Attachment(
                        type="image", url=sticker.url, name=f"{sticker.name}.png"
                    )
                )
            elif sticker.format == discord.StickerFormatType.gif:
                attachments.append(
                    Attachment(
                        type="image", url=sticker.url, name=f"{sticker.name}.gif"
                    )
                )
            elif sticker.format == discord.StickerFormatType.lottie:
                label = sticker.name
                if text.strip():
                    text += f"\n[Sticker: {label}]"
                else:
                    text = f"[Sticker: {label}]"
                self.logger.debug(
                    f"sticker '{label}' is Lottie format, cannot bridge as image"
                )

        if text:
            text, emoji_attachments = _extract_custom_emojis(text)
            attachments.extend(emoji_attachments)

        if not attachments:
            text, attachments = await self._extract_auto_link_image(text)

        if not text.strip() and not attachments:
            self.logger.debug(f"ignoring empty message from {message.author}")
            return

        avatar = (
            str(message.author.display_avatar.url)
            if message.author.display_avatar
            else ""
        )

        mentions = []
        for u in message.mentions:
            mentions.append({"id": str(u.id), "name": u.display_name})

        msg = NormalizedMessage(
            platform="discord",
            instance_id=self.instance_id,
            channel={"server_id": server_id, "channel_id": channel_id},
            nickname=message.author.display_name,
            user_id=str(message.author.id),
            user_avatar=avatar,
            text=text,
            attachments=attachments,
            message_id=str(message.id),
            reply_parent=str(message.reference.message_id)
            if message.reference and not is_forward
            else None,
            mentions=mentions,
            source_proxy=self._media_proxy,
            username=message.author.name,
            is_dm=server_id == "",
        )
        await self.bridge.on_message(msg)

    @staticmethod
    def _is_content_edit(before: discord.Message, after: discord.Message) -> bool:
        """Return whether a MESSAGE_UPDATE reflects a real content edit.

        Discord dispatches ``on_message_edit`` for events that are not user
        edits, most notably pinning/unpinning a message (标注) and the
        auto-generated link embeds/previews. Those updates leave the message
        text and attachments untouched, so we compare the meaningful fields and
        ignore updates that only change ``pinned``/``embeds``.
        """
        if before.content != after.content:
            return True
        # Attachments can change on a genuine edit (e.g. removing an image).
        before_atts = {a.id for a in before.attachments}
        after_atts = {a.id for a in after.attachments}
        if before_atts != after_atts:
            return True
        return False

    async def _on_message_edit(self, message: discord.Message):
        server_id = str(message.guild.id) if message.guild else ""
        channel_id = str(message.channel.id)
        text = message.clean_content
        if not text.strip():
            return
        from services.message import NormalizedMessage as NM

        avatar = (
            str(message.author.display_avatar.url)
            if message.author.display_avatar
            else ""
        )
        msg = NM(
            platform="discord",
            instance_id=self.instance_id,
            channel={"server_id": server_id, "channel_id": channel_id},
            nickname=message.author.display_name,
            user_id=str(message.author.id),
            user_avatar=avatar,
            text=text,
            message_id=str(message.id),
            edit_target_id=str(message.id),
            is_edit=True,
            username=message.author.name,
            is_dm=server_id == "",
        )
        await self.bridge.on_edit_message(msg)

    async def _on_message_pin(self, message: discord.Message, pinned: bool):
        msg_id = str(message.id)
        if pinned and msg_id in self._pin_suppress:
            self._pin_suppress.discard(msg_id)
            return
        server_id = str(message.guild.id) if message.guild else ""
        channel_id = str(message.channel.id)
        from services.message import NormalizedMessage as NM

        if pinned:
            msg = NM(
                platform="discord",
                instance_id=self.instance_id,
                channel={"server_id": server_id, "channel_id": channel_id},
                message_id=msg_id,
                pin_target_id=msg_id,
                is_pin=True,
            )
            await self.bridge.on_pin_message(msg)
        else:
            msg = NM(
                platform="discord",
                instance_id=self.instance_id,
                channel={"server_id": server_id, "channel_id": channel_id},
                message_id=msg_id,
                unpin_target_id=msg_id,
                is_unpin=True,
            )
            await self.bridge.on_unpin_message(msg)

    async def _on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        """Bridge a Discord message deletion as a recall.

        Uses the *raw* event so deletions of messages not in the client cache
        are still detected.
        """
        if not self.config.enable_recall:
            return

        message_id = str(payload.message_id)
        # Ignore deletions we performed ourselves (bridged recalls) to avoid a
        # loop where our own delete triggers another recall dispatch.
        if message_id in self._recall_suppress:
            self._recall_suppress.discard(message_id)
            return

        server_id = str(payload.guild_id) if payload.guild_id else ""
        channel_id = str(payload.channel_id)
        from services.message import NormalizedMessage as NM

        msg = NM(
            platform="discord",
            instance_id=self.instance_id,
            channel={"server_id": server_id, "channel_id": channel_id},
            message_id=message_id,
            recall_target_id=message_id,
            is_recall=True,
            is_dm=server_id == "",
        )
        await self.bridge.on_recall_message(msg)

    async def _extract_auto_link_image(self, text: str) -> tuple[str, list[Attachment]]:
        link = text.strip()
        if not link or not _SINGLE_URL_RE.match(link):
            return text, []

        parsed = urlparse(link)
        if not parsed.hostname or not _host_matches(
            parsed.hostname, self.config.auto_link_image_hosts
        ):
            return text, []
        if self._session is None:
            return text, []

        image_url = await self._resolve_link_image_url(link)
        if not image_url:
            return text, []

        bridged_text = text if self.config.auto_link_image_show_original_url else ""
        name = Path(urlparse(image_url).path).name or "image"
        return bridged_text, [Attachment(type="image", url=image_url, name=name)]

    async def _resolve_link_image_url(self, url: str) -> str | None:
        if self._session is None:
            return None
        try:
            async with self._session.get(
                url,
                proxy=self._media_proxy,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status >= 400:
                    return None
                content_type = resp.headers.get("content-type", "").lower()
                final_url = str(resp.url)
                if content_type.startswith("image/"):
                    return final_url
                if "html" not in content_type:
                    return None
                body = await resp.text(errors="ignore")
        except Exception as exc:
            self.logger.debug(
                f"Discord [{self.instance_id}] auto link image resolve failed for {url}: {exc}"
            )
            return None

        for pattern in (_META_IMAGE_RE, _META_IMAGE_REVERSE):
            match = pattern.search(body)
            if not match:
                continue
            image_url = unescape(match.group(1)).strip()
            if image_url.startswith(("http://", "https://")):
                return image_url
        return None

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
                (Path(get_data_path()) / "discord_emojis.json").read_text(
                    encoding="utf-8"
                )
            )
            if isinstance(raw, dict) and "items" in raw:
                # Discord API export format
                for item in raw["items"]:
                    name = item.get("name", "")
                    eid = item.get("id", "")
                    if name and eid:
                        self._emoji_db[name] = eid
            elif isinstance(raw, dict):
                # Simple {face_id: emoji_id | {name, id}} map
                for face_id, entry in raw.items():
                    if isinstance(entry, str):
                        self._emoji_db[f"cqface{face_id}"] = entry
                    elif isinstance(entry, dict):
                        name = entry.get("name", f"cqface{face_id}")
                        eid = entry.get("id", "")
                        if eid:
                            self._emoji_db[name] = eid
        except FileNotFoundError:
            pass
        except Exception as exc:
            self.logger.opt(exception=exc).warning("failed to read emoji DB")

        return self._emoji_db

    def _resolve_cqface(self, face_id: str) -> str:
        """Return the Discord emoji string for a CQ face ID.

        Lookup order:
        1. In-process cache (populated by previous calls).
        2. ``data/discord_emojis.json`` indexed by emoji name ``cqface<id>``.
        3. Walk every guild the bot is connected to and search for a custom
           emoji whose name is ``cqface<id>``.
                4. Fall back to the Unicode mapping in ``db/cqface-map.yaml``.
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

        return cqface.resolve_cqface(face_id)

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
        has_cqface = bool(re.search(r":cqface\d+:", text))
        reply_to_id = kwargs.get("reply_to_id")
        force_bot = False

        # Discord webhook mode does not support specifying reply targets.
        # If bot client is available, prefer bot send for reply messages.
        if reply_to_id and self._client is not None and self.config.send_replies_as_bot:
            force_bot = True
            self.logger.debug(f"forcing bot send for reply reference={reply_to_id}")

        # If webhook fallback is set to bot, prefer bot send when cqface is present.
        if has_cqface and self._send_method == "webhook":
            if self.config.cqface_webhook_fallback == "bot":
                if self._client is not None:
                    force_bot = True
                else:
                    self.logger.warning(
                        "cqface webhook fallback set to bot, "
                        "but bot_token is unavailable; using unicode fallback"
                    )

        # Get webhook_url from rule msg config (kwargs) or channel dict
        webhook_url = kwargs.get("webhook_url") or channel.get("webhook_url")

        # Resolve the send path first so we know which format override to apply
        is_webhook_send = (
            self._send_method == "webhook" and webhook_url is not None and not force_bot
        )

        # Bridge formats by expected send path. If we switch from webhook to bot
        # (e.g. reply bridging), re-apply bot formatting here so bot_msg_format/
        # msg_format and richheader still work.
        if force_bot and self._send_method == "webhook" and webhook_url is not None:
            fmt = kwargs.get("bot_msg_format") or kwargs.get("msg_format")
            if isinstance(fmt, str) and fmt:
                username_value = kwargs.get("username", "")
                if isinstance(username_value, str):
                    username_value = username_value.strip()
                else:
                    username_value = str(username_value or "")
                if not username_value:
                    username_value = str(kwargs.get("user_id") or "")
                ctx = {
                    "platform": kwargs.get("platform"),
                    "instance_id": kwargs.get("instance_id"),
                    "from": kwargs.get("from"),
                    "user": kwargs.get("user"),
                    "username": username_value,
                    "user_id": kwargs.get("user_id"),
                    "user_avatar": kwargs.get("user_avatar"),
                    "msg": kwargs.get("msg"),
                    "time": kwargs.get("time"),
                }
                try:
                    text = fmt.format(**ctx)
                except KeyError as e:
                    self.logger.warning(
                        f"bot format missing key {e}; using incoming text"
                    )
                else:
                    text, parsed_rich_header = parse_richheader_tag(text)
                    if parsed_rich_header is not None:
                        parsed_rich_header["avatar"] = kwargs.get("user_avatar") or ""
                        kwargs["rich_header"] = parsed_rich_header

        # Note: webhook_msg_format and bot_msg_format are handled by bridge.py
        # The 'text' parameter passed here is already formatted

        # Expand :cqface<id>: tokens into proper Discord custom emoji strings
        # when sending via bot; webhook fallback can stay Unicode.
        if has_cqface and (self._send_method == "bot" or force_bot):
            text = self._expand_cqface_emojis(text)
        elif has_cqface and self._send_method == "webhook":
            text = cqface.replace_cqface_tokens(text)

        rich_header = kwargs.get("rich_header")
        if rich_header:
            text = apply_rich_header(text, rich_header, style="markdown")

        # Handle mentions: replace @Name with <@id>
        mentions = list(kwargs.get("mentions", []))

        # Fallback conversion for source "@self_id" mentions.
        # Bridge passes source mention display names, and we map them to the
        # current Discord bot account mention when available.
        source_self_mention_names = kwargs.get("source_self_mention_names", [])
        if source_self_mention_names and self._client and self._client.user:
            bot_id = str(self._client.user.id)
            existing_names = {
                str(m.get("name", "")).strip() for m in mentions if isinstance(m, dict)
            }
            for raw_name in source_self_mention_names:
                name = str(raw_name).strip()
                if not name or name in existing_names:
                    continue
                mentions.append({"id": bot_id, "name": name})
                existing_names.add(name)

        for m in mentions:
            text = text.replace(f"@{m['name']}", f"<@{m['id']}>")

        if self.config.sanitize_mass_mentions:
            text, had_mass_mentions = _sanitize_mass_mentions(text)
            if had_mass_mentions:
                self.logger.warning(
                    "blocked @everyone/@here mention in outgoing message"
                )

        if is_webhook_send:
            assert webhook_url is not None  # Type narrowing for type checker
            if reply_to_id:
                self.logger.debug(
                    "webhook send does not support "
                    "reply reference; sending as normal message. "
                    "Set send_replies_as_bot=true with bot_token for reply bridging."
                )
            # Remove webhook_url from kwargs to avoid duplicate argument
            webhook_kwargs = {k: v for k, v in kwargs.items() if k != "webhook_url"}
            return await self._send_webhook(
                channel, text, attachments, webhook_url, **webhook_kwargs
            )
        elif self._client is not None:
            return await self._send_bot(channel, text, attachments, **kwargs)
        else:
            self.logger.warning("no send method available")
            return None

    async def _send_webhook(
        self,
        channel: dict,
        text: str,
        attachments: list[Attachment] | None,
        webhook_url: str,
        **kwargs,
    ):
        if self._session is None or not webhook_url:
            return None

        payload: dict = {
            "content": text,
            "allowed_mentions": {"parse": self._allowed_mentions_parse()},
        }

        # Format webhook_title and webhook_avatar if they are format strings
        ctx = {
            "platform": kwargs.get("platform"),
            "instance_id": kwargs.get("instance_id"),
            "from": kwargs.get("from"),
            "user": kwargs.get("user"),
            "user_id": kwargs.get("user_id"),
            "user_avatar": kwargs.get("user_avatar"),
            "msg": kwargs.get("msg"),
            "time": kwargs.get("time"),
        }

        if title := kwargs.get("webhook_title"):
            if isinstance(title, str) and "{" in title:
                try:
                    payload["username"] = title.format(**ctx)
                except KeyError as e:
                    self.logger.warning(
                        f"webhook_title missing key {e}; using raw title"
                    )
                    payload["username"] = title
            else:
                payload["username"] = title

        if avatar := kwargs.get("webhook_avatar"):
            if isinstance(avatar, str) and "{" in avatar:
                try:
                    payload["avatar_url"] = avatar.format(**ctx)
                except KeyError as e:
                    self.logger.warning(
                        f"webhook_avatar missing key {e}; using raw avatar"
                    )
                    payload["avatar_url"] = avatar
            else:
                payload["avatar_url"] = avatar

        # Download attachments concurrently; collect as (bytes, mime, filename)
        files: list[tuple[bytes, str, str]] = []
        source_proxy = self._source_proxy_from_kwargs(kwargs)
        valid_atts = [
            att
            for att in attachments or []
            if att.url or att.name or att.data is not None
        ]

        async def _fetch(att: Attachment):
            return await media.fetch_attachment(
                att, self.config.max_file_size, source_proxy
            )

        results = await asyncio.gather(*(_fetch(att) for att in valid_atts))
        for att, result in zip(valid_atts, results):
            if result:
                data_bytes, mime = result
                fname = media.filename_for(att.name, mime)
                files.append((data_bytes, mime, fname))
            else:
                # Size exceeded or download failed — append URL or name as text
                label = att.name or att.url
                ref = f"({att.url})" if att.url else ""
                payload["content"] += f"\n[{att.type.capitalize()}: {label}]{ref}"

        url = webhook_url + ("&" if "?" in webhook_url else "?") + "wait=true"

        try:
            self.logger.debug(
                f"webhook payload overrides: "
                f"username={payload.get('username')!r}, "
                f"avatar_url is {'set' if payload.get('avatar_url') else 'unset'}"
            )
            if files:
                form = aiohttp.FormData()
                form.add_field(
                    "payload_json", json.dumps(payload), content_type="application/json"
                )
                for i, (data_bytes, mime, fname) in enumerate(files):
                    form.add_field(
                        f"files[{i}]", data_bytes, filename=fname, content_type=mime
                    )
                async with self._session.post(url, data=form) as resp:
                    if resp.status in (200, 204, 201):
                        data = await resp.json()
                        author = data.get("author") or {}
                        self.logger.debug(
                            f"webhook sent message "
                            f"id={data.get('id')} author={author.get('username')!r}"
                        )
                        return str(data.get("id", ""))
                    body = await resp.text()
                    self.logger.error(f"webhook error {resp.status}: {body}")
            else:
                async with self._session.post(url, json=payload) as resp:
                    if resp.status in (200, 204, 201):
                        data = await resp.json()
                        author = data.get("author") or {}
                        self.logger.debug(
                            f"webhook sent message "
                            f"id={data.get('id')} author={author.get('username')!r}"
                        )
                        return str(data.get("id", ""))
                    body = await resp.text()
                    self.logger.error(f"webhook error {resp.status}: {body}")
        except Exception:
            self.logger.exception("webhook exception")
        return None

    async def _send_bot(
        self,
        channel: dict,
        text: str,
        attachments: list[Attachment] | None,
        **kwargs,
    ):
        if self._client is None:
            return None
        channel_id = channel.get("channel_id")
        if not channel_id:
            self.logger.warning("send_bot: no channel_id")
            return None
        ch = self._client.get_channel(int(channel_id))
        if ch is None:
            try:
                ch = await self._client.fetch_channel(int(channel_id))
            except Exception as e:
                self.logger.warning(f"could not fetch channel {channel_id}: {e}")
                return None

        # Ensure the channel is messageable (has a send method)
        if not isinstance(ch, discord.abc.Messageable):
            self.logger.warning(f"channel {channel_id} is not messageable")
            return None

        discord_files: list[discord.File] = []
        source_proxy = self._source_proxy_from_kwargs(kwargs)
        valid_atts = [
            att
            for att in attachments or []
            if att.url or att.name or att.data is not None
        ]

        async def _fetch(att: Attachment):
            return await media.fetch_attachment(
                att, self.config.max_file_size, source_proxy
            )

        results = await asyncio.gather(*(_fetch(att) for att in valid_atts))
        for att, result in zip(valid_atts, results):
            if result:
                data_bytes, mime = result
                fname = media.filename_for(att.name, mime)
                discord_files.append(
                    discord.File(io.BytesIO(data_bytes), filename=fname)
                )
            else:
                label = att.name or att.url
                ref = f"({att.url})" if att.url else ""
                text += f"\n[{att.type.capitalize()}: {label}]{ref}"

        reply_to_id = kwargs.get("reply_to_id")
        reference = None
        if reply_to_id:
            try:
                # We need a partial message for reference
                reference = discord.MessageReference(
                    message_id=int(reply_to_id), channel_id=int(channel_id)
                )
            except (ValueError, TypeError):
                pass

        try:
            replied_user = True
            source_mentioned_self = kwargs.get("source_mentioned_self")
            if source_mentioned_self is not None:
                replied_user = bool(source_mentioned_self)

            allowed = discord.AllowedMentions(
                everyone=self.config.allow_mentions_everyone,
                users=self.config.allow_mentions_users,
                roles=self.config.allow_mentions_roles,
                replied_user=replied_user,
            )

            send_kwargs: dict = {"allowed_mentions": allowed}
            if text:
                send_kwargs["content"] = text
            if discord_files:
                send_kwargs["files"] = discord_files
            if reference is not None:
                send_kwargs["reference"] = reference
            sent = await ch.send(**send_kwargs)  # type: ignore[no-matching-overload]
            return str(sent.id)
        except Exception:
            self.logger.exception("send error")
        return None

    # ------------------------------------------------------------------
    # Edit
    # ------------------------------------------------------------------

    async def edit(self, channel: dict, message_id: str, text: str, **kwargs):
        """Edit a previously sent message by ID."""
        webhook_url = kwargs.get("webhook_url") or channel.get("webhook_url")

        has_cqface = bool(re.search(r":cqface\d+:", text))
        rich_header = kwargs.get("rich_header")

        if webhook_url and self._session is not None:
            if has_cqface:
                text = cqface.replace_cqface_tokens(text)
            if rich_header:
                text = apply_rich_header(text, rich_header, style="markdown")
            if self.config.sanitize_mass_mentions:
                text, _ = _sanitize_mass_mentions(text)
            base = webhook_url.split("?")[0].rstrip("/")
            edit_url = f"{base}/messages/{message_id}"
            payload = {"content": text}
            try:
                async with self._session.patch(edit_url, json=payload) as resp:
                    if resp.status not in (200, 204):
                        body = await resp.text()
                        self.logger.error(f"webhook edit error {resp.status}: {body}")
            except Exception:
                self.logger.exception(f"edit: webhook PATCH failed for {message_id}")
            return

        if self._client is None:
            self.logger.debug("edit: no webhook_url and no bot client, skipping")
            return

        channel_id = channel.get("channel_id")
        if not channel_id:
            self.logger.warning("edit: no channel_id")
            return

        ch = self._client.get_channel(int(channel_id))
        if ch is None:
            try:
                ch = await self._client.fetch_channel(int(channel_id))
            except Exception as e:
                self.logger.warning(f"edit: could not fetch channel {channel_id}: {e}")
                return

        if not isinstance(ch, discord.abc.Messageable):
            return

        try:
            msg_obj = await ch.fetch_message(int(message_id))  # type: ignore[attr-defined]
        except Exception as e:
            self.logger.warning(f"edit: could not fetch message {message_id}: {e}")
            return

        if has_cqface:
            text = self._expand_cqface_emojis(text)
        if rich_header:
            text = apply_rich_header(text, rich_header, style="markdown")
        if self.config.sanitize_mass_mentions:
            text, _ = _sanitize_mass_mentions(text)

        try:
            await msg_obj.edit(content=text)
        except Exception:
            self.logger.exception(f"edit: failed to edit message {message_id}")

    # ------------------------------------------------------------------
    # Delete / recall
    # ------------------------------------------------------------------

    async def pin(self, channel: dict, target_msg_id: str):
        if self._client is None:
            self.logger.debug("pin: no bot client, skipping")
            return

        channel_id = channel.get("channel_id")
        if not channel_id:
            self.logger.warning("pin: no channel_id")
            return

        ch = self._client.get_channel(int(channel_id))
        if ch is None:
            try:
                ch = await self._client.fetch_channel(int(channel_id))
            except Exception as e:
                self.logger.warning(f"pin: could not fetch channel {channel_id}: {e}")
                return

        if not isinstance(ch, discord.abc.Messageable):
            return

        try:
            msg_obj = await ch.fetch_message(int(target_msg_id))
            self._bounded_add(self._pin_suppress, target_msg_id)
            await msg_obj.pin()
        except discord.Forbidden:
            self.logger.warning(f"pin: no permission to pin in {channel_id}")
        except Exception as e:
            self.logger.warning(f"pin: failed to pin message {target_msg_id}: {e}")

    async def unpin(self, channel: dict, target_msg_id: str):
        if self._client is None:
            self.logger.debug("unpin: no bot client, skipping")
            return

        channel_id = channel.get("channel_id")
        if not channel_id:
            self.logger.warning("unpin: no channel_id")
            return

        ch = self._client.get_channel(int(channel_id))
        if ch is None:
            try:
                ch = await self._client.fetch_channel(int(channel_id))
            except Exception as e:
                self.logger.warning(f"unpin: could not fetch channel {channel_id}: {e}")
                return

        if not isinstance(ch, discord.abc.Messageable):
            return

        try:
            msg_obj = await ch.fetch_message(int(target_msg_id))
            await msg_obj.unpin()
        except discord.Forbidden:
            self.logger.warning(f"unpin: no permission to unpin in {channel_id}")
        except Exception as e:
            self.logger.warning(f"unpin: failed to unpin message {target_msg_id}: {e}")

    async def delete(self, channel: dict, message_id: str, **kwargs):
        """Delete (recall) a previously sent message by ID."""
        if not self.config.enable_recall or not message_id:
            return

        # Suppress the raw delete event Discord dispatches back for this action.
        self._bounded_add(self._recall_suppress, str(message_id))

        webhook_url = kwargs.get("webhook_url") or channel.get("webhook_url")

        if webhook_url and self._session is not None:
            base = webhook_url.split("?")[0].rstrip("/")
            delete_url = f"{base}/messages/{message_id}"
            try:
                async with self._session.delete(delete_url) as resp:
                    if resp.status not in (200, 204, 404):
                        body = await resp.text()
                        self.logger.error(f"webhook delete error {resp.status}: {body}")
            except Exception:
                self._recall_suppress.discard(str(message_id))
                self.logger.exception(f"delete: webhook DELETE failed for {message_id}")
            return

        if self._client is None:
            self._recall_suppress.discard(str(message_id))
            self.logger.debug("delete: no webhook_url and no bot client, skipping")
            return

        channel_id = channel.get("channel_id")
        if not channel_id:
            self._recall_suppress.discard(str(message_id))
            self.logger.warning("delete: no channel_id")
            return

        ch = self._client.get_channel(int(channel_id))
        if ch is None:
            try:
                ch = await self._client.fetch_channel(int(channel_id))
            except Exception as e:
                self._recall_suppress.discard(str(message_id))
                self.logger.warning(
                    f"delete: could not fetch channel {channel_id}: {e}"
                )
                return

        if not isinstance(ch, discord.abc.Messageable):
            self._recall_suppress.discard(str(message_id))
            return

        try:
            msg_obj = await ch.fetch_message(int(message_id))  # type: ignore[attr-defined]
        except Exception as e:
            self._recall_suppress.discard(str(message_id))
            self.logger.warning(f"delete: could not fetch message {message_id}: {e}")
            return

        try:
            await msg_obj.delete()
        except Exception:
            self._recall_suppress.discard(str(message_id))
            self.logger.exception(f"delete: failed to delete message {message_id}")


register("discord", DiscordConfig, DiscordDriver)
