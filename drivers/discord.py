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
import io
import json
from pathlib import Path
import re

import discord
import aiohttp

from typing import Literal

from pydantic import field_validator

import services.logger as log
import services.cqface as cqface
import services.media as media
from services.message import Attachment, NormalizedMessage
from services.util import get_data_path
from services.config_schema import _DriverConfig, CoercedBool
from services.config import get_proxy, UNSET
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


logger = log.get_logger()

_CQFACE_RE = re.compile(r":cqface(\d+):")
_RICHHEADER_RE = re.compile(r"<richheader\b([^/]*)/>", re.IGNORECASE)
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
_MASS_MENTION_RE = re.compile(r"@(everyone|here)\b", re.IGNORECASE)


def _parse_richheader(text: str) -> tuple[str, dict | None]:
    m = _RICHHEADER_RE.search(text)
    if not m:
        return text, None
    attrs = dict(_ATTR_RE.findall(m.group(1)))
    clean = (text[: m.start()] + text[m.end() :]).strip()
    return clean, attrs or None


def _sanitize_mass_mentions(text: str) -> tuple[str, bool]:
    """Neutralize @everyone/@here so they cannot trigger mass pings."""
    sanitized, count = _MASS_MENTION_RE.subn(lambda m: f"@ {m.group(1)}", text)
    return sanitized, count > 0


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
        # name → emoji_id index built lazily from discord_emojis.json
        self._emoji_db: dict[str, str] | None = None

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
        if self._proxy:
            logger.debug(f"Discord [{self.instance_id}] using proxy {self._proxy}")
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=False), proxy=self._proxy
            )
        else:
            self._session = aiohttp.ClientSession()

        if not self._bot_token:
            logger.warning(
                f"Discord [{self.instance_id}] no bot_token configured — "
                "receive disabled, send-only via webhook"
            )
            return  # Webhook-only: session stays open, send() will be called by bridge

        intents = discord.Intents.default()
        intents.message_content = True
        if self._proxy:
            self._client = discord.Client(intents=intents, proxy=self._proxy)
        else:
            self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready():
            assert self._client is not None  # Type narrowing
            logger.info(
                f"Discord [{self.instance_id}] logged in as {self._client.user}"
            )

        @self._client.event
        async def on_message(message: discord.Message):
            if message.author.bot:
                # logger.debug(
                #     f"Discord [{self.instance_id}] ignoring bot message from {message.author}"
                # )
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
        logger.debug(
            f"Discord [{self.instance_id}] message from {message.author} "
            f"server={server_id} channel={channel_id}"
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

        if not text.strip() and not attachments:
            logger.debug(
                f"Discord [{self.instance_id}] ignoring empty message from {message.author}"
            )
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
            if message.reference
            else None,
            mentions=mentions,
            source_proxy=self._media_proxy,
            username=message.author.name,
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
            logger.opt(exception=exc).warning(
                f"Discord [{self.instance_id}] failed to read emoji DB"
            )

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
            logger.debug(
                f"Discord [{self.instance_id}] forcing bot send for reply "
                f"reference={reply_to_id}"
            )

        # If webhook fallback is set to bot, prefer bot send when cqface is present.
        if has_cqface and self._send_method == "webhook":
            if self.config.cqface_webhook_fallback == "bot":
                if self._client is not None:
                    force_bot = True
                else:
                    logger.warning(
                        f"Discord [{self.instance_id}] cqface webhook fallback set to bot, "
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
                    logger.warning(
                        f"Discord [{self.instance_id}] bot format missing key {e}; using incoming text"
                    )
                else:
                    text, parsed_rich_header = _parse_richheader(text)
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
            t, c = rich_header.get("title", ""), rich_header.get("content", "")
            prefix = f"**{t}**" + (f" · *{c}*" if c else "")
            text = f"{prefix}\n{text}" if text else prefix

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
                logger.warning(
                    f"Discord [{self.instance_id}] blocked @everyone/@here mention in outgoing message"
                )

        if is_webhook_send:
            assert webhook_url is not None  # Type narrowing for type checker
            if reply_to_id:
                logger.debug(
                    f"Discord [{self.instance_id}] webhook send does not support "
                    f"reply reference; sending as normal message. "
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
            logger.warning(f"Discord [{self.instance_id}] no send method available")
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
                    logger.warning(f"webhook_title missing key {e}; using raw title")
                    payload["username"] = title
            else:
                payload["username"] = title

        if avatar := kwargs.get("webhook_avatar"):
            if isinstance(avatar, str) and "{" in avatar:
                try:
                    payload["avatar_url"] = avatar.format(**ctx)
                except KeyError as e:
                    logger.warning(f"webhook_avatar missing key {e}; using raw avatar")
                    payload["avatar_url"] = avatar
            else:
                payload["avatar_url"] = avatar

        # Download each attachment; collect as (bytes, mime, filename) triples
        files: list[tuple[bytes, str, str]] = []
        source_proxy = self._source_proxy_from_kwargs(kwargs)
        for att in attachments or []:
            if not att.url and att.data is None:
                continue
            result = await media.fetch_attachment(
                att, self.config.max_file_size, source_proxy
            )
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
            logger.debug(
                f"Discord [{self.instance_id}] webhook payload overrides: "
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
                        logger.debug(
                            f"Discord [{self.instance_id}] webhook sent message "
                            f"id={data.get('id')} author={author.get('username')!r}"
                        )
                        return str(data.get("id", ""))
                    body = await resp.text()
                    logger.error(
                        f"Discord [{self.instance_id}] webhook error {resp.status}: {body}"
                    )
            else:
                async with self._session.post(url, json=payload) as resp:
                    if resp.status in (200, 204, 201):
                        data = await resp.json()
                        author = data.get("author") or {}
                        logger.debug(
                            f"Discord [{self.instance_id}] webhook sent message "
                            f"id={data.get('id')} author={author.get('username')!r}"
                        )
                        return str(data.get("id", ""))
                    body = await resp.text()
                    logger.error(
                        f"Discord [{self.instance_id}] webhook error {resp.status}: {body}"
                    )
        except Exception:
            logger.exception(f"Discord [{self.instance_id}] webhook exception")
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
            logger.warning(f"Discord [{self.instance_id}] send_bot: no channel_id")
            return None
        ch = self._client.get_channel(int(channel_id))
        if ch is None:
            try:
                ch = await self._client.fetch_channel(int(channel_id))
            except Exception as e:
                logger.warning(
                    f"Discord [{self.instance_id}] could not fetch channel {channel_id}: {e}"
                )
                return None

        # Ensure the channel is messageable (has a send method)
        if not isinstance(ch, discord.abc.Messageable):
            logger.warning(
                f"Discord [{self.instance_id}] channel {channel_id} is not messageable"
            )
            return None

        discord_files: list[discord.File] = []
        source_proxy = self._source_proxy_from_kwargs(kwargs)
        for att in attachments or []:
            if not att.url and att.data is None:
                continue
            result = await media.fetch_attachment(
                att, self.config.max_file_size, source_proxy
            )
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
            # Build kwargs to only include non-None/non-empty values
            send_kwargs = {}
            if text:
                send_kwargs["content"] = text
            if discord_files:
                send_kwargs["files"] = discord_files
            if reference is not None:
                send_kwargs["reference"] = reference

            replied_user = True
            source_mentioned_self = kwargs.get("source_mentioned_self")
            if source_mentioned_self is not None:
                replied_user = bool(source_mentioned_self)

            send_kwargs["allowed_mentions"] = discord.AllowedMentions(
                everyone=self.config.allow_mentions_everyone,
                users=self.config.allow_mentions_users,
                roles=self.config.allow_mentions_roles,
                replied_user=replied_user,
            )

            sent = await ch.send(**send_kwargs)
            return str(sent.id)
        except Exception:
            logger.exception(f"Discord [{self.instance_id}] send error")
        return None


register("discord", DiscordConfig, DiscordDriver)
