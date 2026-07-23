# Telegram driver via python-telegram-bot (v20+).
# Uses long-polling to receive messages and the bot API to send.
#
# Config keys (under telegram.<instance_id>):
#   bot_token         – Telegram bot token from @BotFather (required)
#   max_file_size     – Max bytes per attachment when sending (default 50 MB,
#                       Telegram bot API limit)
#   rich_header_host  – Base URL of the Cloudflare rich-header worker
#                       (e.g. "https://richheader.yourname.workers.dev" or "https://richheader.siiway.top").
#                       When set, text-only bridged messages whose msg_format
#                       includes a <richheader/> tag are sent with a small OG
#                       link-preview card shown above the text (avatar + name).
#                       Falls back to bold HTML header when absent or when the
#                       message carries media attachments.
#   avatar_proxy_host – Base URL of the Cloudflare Telegram avatar proxy worker
#                       (e.g. "https://tg-avatar-proxy.yourname.workers.dev").
#                       When set, user avatars are proxied through this worker
#                       to avoid exposing the bot token. The worker should be
#                       deployed from cloudflare/tg-avatar-proxy.js with BOT_TOKEN
#                       environment variable set. Falls back to none when absent.
#   photo_padding_color – Padding color used when fixing extreme image aspect
#                       ratios before send_photo (default "#000000").
#                       Set to null to disable padding; over-limit photos are
#                       sent as text labels instead of send_photo.
#
# Rule channel keys:
#   chat_id – Telegram chat ID (negative for groups, e.g. "-100123456789")

import asyncio
import html
import io
import re
from typing import TypedDict
from urllib.parse import urlencode

# Runtime import (not TYPE_CHECKING): httpx.Proxy / httpx.URL are referenced in
# the _HTTPXRequestCommonKwargs annotation below, which is evaluated at import
# time, so removing this import would raise NameError. httpx is a hard dependency
# (declared in pyproject and required by python-telegram-bot).
import httpx
from PIL import Image, UnidentifiedImageError
from telegram import LinkPreviewOptions, ReplyParameters, Update
from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

import services.logger as log
from drivers import BaseDriver
from drivers.registry import register
from services import media
from services.config import UNSET, get_proxy
from services.config_schema import _DriverConfig, CoercedBool
from services.message import Attachment, NormalizedMessage
from services.message_format import telegram_richheader_html


class _HTTPXRequestCommonKwargs(TypedDict, total=False):
    pool_timeout: float | None
    connect_timeout: float | None
    read_timeout: float | None
    write_timeout: float | None
    media_write_timeout: float | None
    proxy: str | httpx.Proxy | httpx.URL | None


def _patch_httpcore_proxy_tunnel():
    """Apply monkey-patch for httpcore connection pool poisoning via proxy TLS failures.

    When a CONNECT-tunneled request fails during start_tls (e.g. ConnectError),
    the tunnel's inner connection is left in an ACTIVE state but can never be
    reused, permanently leaking a connection slot from the pool.
    Once max_connections slots are leaked, every new request hits PoolTimeout.

    See: https://github.com/encode/httpcore/discussions/921
    """
    try:
        # async_mod / sync_mod re-export httpcore's Request / Response types, so
        # the patched handlers' annotations below stay aligned with httpcore
        # without needing a separate (TYPE_CHECKING) httpcore import.
        import httpcore._async.http_proxy as async_mod
        import httpcore._sync.http_proxy as sync_mod
    except ImportError:
        return

    _orig_async_handle = async_mod.AsyncTunnelHTTPConnection.handle_async_request

    async def _patched_async_handle(
        self: async_mod.AsyncTunnelHTTPConnection,
        request: async_mod.Request,
    ) -> async_mod.Response:
        try:
            return await _orig_async_handle(self, request)
        except Exception:
            if not getattr(self, "_connected", True):
                try:
                    await self._connection.aclose()
                except Exception:
                    pass
            raise

    setattr(
        async_mod.AsyncTunnelHTTPConnection,
        "handle_async_request",
        _patched_async_handle,
    )

    _orig_sync_handle = sync_mod.TunnelHTTPConnection.handle_request

    def _patched_sync_handle(
        self: sync_mod.TunnelHTTPConnection,
        request: sync_mod.Request,
    ) -> sync_mod.Response:
        try:
            return _orig_sync_handle(self, request)
        except Exception:
            if not getattr(self, "_connected", True):
                try:
                    self._connection.close()
                except Exception:
                    pass
            raise

    setattr(
        sync_mod.TunnelHTTPConnection,
        "handle_request",
        _patched_sync_handle,
    )


_patch_httpcore_proxy_tunnel()


class TelegramConfig(_DriverConfig):
    bot_token: str
    max_file_size: int = 50 * 1024 * 1024
    rich_header_host: str = "https://richheader.siiway.top"
    avatar_proxy_host: str = ""  # Base URL for avatar proxy (e.g. "https://avatarproxy.yourname.workers.dev")
    photo_padding_color: str | None = "#000000"
    sanitize_accidental_mentions: CoercedBool = True
    # When enabled, a recall bridged from another platform deletes the matching
    # Telegram message. Note: the Telegram Bot API cannot notify us when a user
    # deletes a message, so recalls cannot be *detected* from Telegram sources.
    enable_recall: CoercedBool = True
    proxy: str | None = UNSET


_TG_PHOTO_MAX_SIDE = 10000
_TG_PHOTO_MAX_RATIO = 20

_logger = log.get_logger("telegram")


# Catch all non-command message types that may carry content


def _prepare_photo_for_telegram(
    data: bytes, filename: str, padding_color: str | None
) -> tuple[bytes | None, str]:
    """Adjust photo dimensions for Telegram bot API constraints."""
    if Image is None:
        return data, filename

    try:
        with Image.open(io.BytesIO(data)) as img:
            mode = "RGBA" if "A" in img.getbands() else "RGB"
            work = img.convert(mode)
            width, height = work.size

            over_side_limit = width > _TG_PHOTO_MAX_SIDE or height > _TG_PHOTO_MAX_SIDE
            over_ratio_limit = (
                width > height * _TG_PHOTO_MAX_RATIO
                or height > width * _TG_PHOTO_MAX_RATIO
            )
            if (over_side_limit or over_ratio_limit) and padding_color is None:
                return None, filename

            changed = False

            # Telegram rejects photos with side > 10000.
            if width > _TG_PHOTO_MAX_SIDE or height > _TG_PHOTO_MAX_SIDE:
                scale = min(_TG_PHOTO_MAX_SIDE / width, _TG_PHOTO_MAX_SIDE / height)
                width = max(1, int(width * scale))
                height = max(1, int(height * scale))
                # Pillow>=9 uses Image.Resampling; older versions expose constants on Image.
                if hasattr(Image, "Resampling"):
                    resampling = Image.Resampling.LANCZOS
                else:
                    resampling = Image.LANCZOS
                work = work.resize((width, height), resampling)
                changed = True

            target_w, target_h = width, height
            if width > height * _TG_PHOTO_MAX_RATIO:
                target_h = (width + _TG_PHOTO_MAX_RATIO - 1) // _TG_PHOTO_MAX_RATIO
            elif height > width * _TG_PHOTO_MAX_RATIO:
                target_w = (height + _TG_PHOTO_MAX_RATIO - 1) // _TG_PHOTO_MAX_RATIO

            if target_w != width or target_h != height:
                bg = _parse_padding_color(padding_color, mode)
                canvas = Image.new(mode, (target_w, target_h), bg)
                offset = ((target_w - width) // 2, (target_h - height) // 2)
                if mode == "RGBA":
                    canvas.paste(work, offset, work)
                else:
                    canvas.paste(work, offset)
                work = canvas
                changed = True

            if not changed:
                return data, filename

            out = io.BytesIO()
            base = (
                filename.rsplit(".", 1)[0] if "." in filename else (filename or "photo")
            )
            if mode == "RGBA":
                work.save(out, format="PNG")
                out_name = f"{base}.png"
            else:
                work.save(out, format="JPEG", quality=95)
                out_name = f"{base}.jpg"
            return out.getvalue(), out_name
    except UnidentifiedImageError:
        return data, filename
    except Exception as e:
        _logger.debug(f"image preprocess skipped for {filename}: {e}")
        return data, filename


def _parse_padding_color(color: str | None, mode: str) -> tuple[int, ...]:
    """Parse padding color from config; supports #RGB/#RRGGBB/#RRGGBBAA and r,g,b[,a]."""
    value = (color or "").strip()
    rgb = (0, 0, 0)
    rgba = (0, 0, 0, 255)

    try:
        if value.startswith("#"):
            hex_value = value[1:]
            match len(hex_value):
                case 3:
                    r, g, b = (int(ch * 2, 16) for ch in hex_value)
                    rgb = (r, g, b)
                    rgba = (r, g, b, 255)
                case 6:
                    r = int(hex_value[0:2], 16)
                    g = int(hex_value[2:4], 16)
                    b = int(hex_value[4:6], 16)
                    rgb = (r, g, b)
                    rgba = (r, g, b, 255)
                case 8:
                    r = int(hex_value[0:2], 16)
                    g = int(hex_value[2:4], 16)
                    b = int(hex_value[4:6], 16)
                    a = int(hex_value[6:8], 16)
                    rgb = (r, g, b)
                    rgba = (r, g, b, a)
        elif "," in value:
            parts = [int(p.strip()) for p in value.split(",")]
            if len(parts) >= 3:
                r = min(255, max(0, parts[0]))
                g = min(255, max(0, parts[1]))
                b = min(255, max(0, parts[2]))
                a = min(255, max(0, parts[3])) if len(parts) >= 4 else 255
                rgb = (r, g, b)
                rgba = (r, g, b, a)
    except Exception as exc:
        _logger.warning(f"Parse padding color {color} failed: {exc}")

    return rgba if mode == "RGBA" else rgb


def _attachment_fallback_label(
    att_type: str, label: str, parse_mode: str | None
) -> str:
    """Format a degraded attachment label for text fallback."""
    if parse_mode == "HTML":
        label = html.escape(label)
    display_type = "Image" if att_type == "image" else att_type.capitalize()
    return f"\n[{display_type}: {label}]"


_CONTENT_FILTER = (
    (
        filters.TEXT
        | filters.PHOTO
        | filters.VIDEO
        | filters.VOICE
        | filters.AUDIO
        | filters.Document.ALL
        | filters.ANIMATION
        | filters.Sticker.ALL
    )
    & ~filters.COMMAND
    & ~filters.UpdateType.EDITED_MESSAGE
)

_COMMAND_FILTER = filters.COMMAND & ~filters.UpdateType.EDITED_MESSAGE


class TelegramDriver(BaseDriver[TelegramConfig]):
    def __init__(self, instance_id: str, config: TelegramConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._app: Application | None = None
        self._proxy = get_proxy(config.proxy)

    async def start(self):
        self.bridge.register_sender(self.instance_id, self.send)
        # Use a dedicated connection pool for long-polling getUpdates
        # to avoid starving the general request pool.
        common_kwargs: _HTTPXRequestCommonKwargs = {
            "pool_timeout": 5.0,
            "connect_timeout": 30.0,
            "read_timeout": 30.0,
            "write_timeout": 30.0,
            "media_write_timeout": 30.0,
            "proxy": self._proxy,
        }
        get_updates_req = HTTPXRequest(connection_pool_size=1, **common_kwargs)
        req = HTTPXRequest(**common_kwargs)
        self._app = (
            Application.builder()
            .token(self.config.bot_token)
            .request(req)
            .get_updates_request(get_updates_req)
            .build()
        )
        self._app.add_handler(MessageHandler(_CONTENT_FILTER, self._on_message))
        self._app.add_handler(MessageHandler(_COMMAND_FILTER, self._on_command_message))
        self._app.add_handler(
            MessageHandler(filters.UpdateType.EDITED_MESSAGE, self._on_edited_message)
        )
        self._app.add_error_handler(self._on_error)

        self.logger.debug("starting application and polling.")

        # ensure bot's get_me is retried on failure
        # error in start/start_polling shouldn't happen, so let it crash if it does
        try:
            while True:
                try:
                    await self._app.initialize()
                    break
                except TelegramError as e:
                    self.logger.error(
                        f"initialization failed: {e}, retrying in 5 seconds..."
                    )
                    await asyncio.sleep(5)
        except asyncio.CancelledError:
            self.logger.debug("initialization cancelled.")
            return
        await self._app.start()
        self.bridge.register_editor(self.instance_id, self.edit)
        if self.config.enable_recall:
            self.bridge.register_deleter(self.instance_id, self.delete)
        assert self._app.updater is not None
        self.logger.debug("application started.")
        await self._app.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            timeout=10,
            bootstrap_retries=10,
        )
        self.logger.debug("polling started.")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.logger.debug("polling cancelled.")
        finally:
            await self.stop()

    async def stop(self):
        if not self._app:
            return
        if self._app.updater and self._app.updater.running:
            await self._app.updater.stop()
        if self._app.running:
            await self._app.stop()
        if not self._app.running:
            await self._app.shutdown()
        self._app = None

    async def _on_error(self, _: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.logger.opt(exception=True).exception(
            "Telegram [%s] handler error", self.instance_id
        )

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    def _is_nextbridge_command_text(self, text: str) -> bool:
        command_text = (text or "").strip()
        if not command_text.startswith("/"):
            return False

        root = command_text[1:].split(maxsplit=1)[0].split("@", 1)[0].lower()
        if root == "ping":
            return True

        prefix = (self.bridge.command_prefix or "nb").strip().lstrip("/").lower()
        if not prefix:
            prefix = "nb"
        return root == prefix

    def _is_recall_command_text(self, text: str) -> bool:
        command_text = (text or "").strip()
        if not command_text.startswith("/"):
            return False
        root = command_text[1:].split(maxsplit=1)[0].split("@", 1)[0].lower()
        return root == "recall"

    async def _on_command_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        msg = update.message
        if not msg or not msg.text:
            return

        # /recall: user-driven recall notification (workaround for the Bot API
        # not delivering deletion updates). Reply to a message with /recall to
        # signal that it should be recalled everywhere.
        if self._is_recall_command_text(msg.text):
            await self._on_recall_command(update, context)
            return

        # Only forward NextBridge built-in commands (/ping and /<prefix> ...).
        if not self._is_nextbridge_command_text(msg.text):
            return

        await self._on_message(update, context)

    async def _on_recall_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if not self.config.enable_recall:
            return
        msg = update.message
        if not msg:
            return
        chat_id = str(msg.chat_id)
        reply = msg.reply_to_message
        if not reply:
            if self._app:
                try:
                    await self._app.bot.send_message(
                        chat_id=int(chat_id),
                        text="用法：回复要撤回的消息并发送 /recall。",
                        reply_to_message_id=msg.message_id,
                    )
                except Exception as e:
                    self.logger.warning(f"recall usage hint failed: {e}")
            return

        target_id = str(reply.message_id)
        normalized = NormalizedMessage(
            platform="telegram",
            instance_id=self.instance_id,
            channel={"chat_id": chat_id},
            message_id=target_id,
            recall_target_id=target_id,
            is_recall=True,
            is_dm=msg.chat_id > 0,
        )
        await self.bridge.on_recall_message(normalized)

        # Also remove the original message and the /recall command message on
        # Telegram itself (best-effort; requires delete permission).
        if self._app:
            for mid in (reply.message_id, msg.message_id):
                try:
                    await self._app.bot.delete_message(
                        chat_id=int(chat_id), message_id=mid
                    )
                except Exception as e:
                    self.logger.warning(f"recall: delete message {mid} failed: {e}")

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg:
            return

        # Media messages use caption instead of text
        text = msg.text or msg.caption or ""

        mentions = []
        entities = msg.entities or msg.caption_entities or []
        for ent in entities:
            match ent.type:
                case "mention":
                    # @username mention
                    # Extract username from text
                    offset = ent.offset
                    length = ent.length
                    username = text[offset : offset + length]  # includes @
                    # We don't have ID for @username mentions easily unless we resolve it
                    # But we can store it as name=username
                    mentions.append({"id": username, "name": username[1:]})
                case "text_mention":
                    # Text link to user
                    user = ent.user
                    if user:
                        uid = str(user.id)
                        name = user.full_name or user.username or uid
                        mentions.append({"id": uid, "name": name})

        chat_id = str(msg.chat_id)
        from_user = msg.from_user
        user_id = str(from_user.id) if from_user else ""
        nickname = (
            (from_user.full_name or from_user.username or user_id)
            if from_user
            else user_id
        )
        username = from_user.username or "" if from_user else ""

        # Get user avatar
        user_avatar = ""
        if from_user and self._app:
            try:
                photos = await self._app.bot.get_user_profile_photos(
                    user_id=int(user_id), limit=1
                )
                if photos.photos:
                    photo = photos.photos[0][-1]  # Get the largest size
                    f = await photo.get_file()

                    # Use avatar proxy if configured
                    if f.file_path and self.config.avatar_proxy_host:
                        host = self.config.avatar_proxy_host.rstrip("/")
                        # file_path should be a relative path like 'photos/file_6.jpg'
                        # If it's a full URL, extract the photos/ or profile_photos/ part
                        file_path = f.file_path
                        self.logger.debug(f"original file_path: {file_path}")
                        if file_path.startswith("http"):
                            from urllib.parse import urlparse

                            parsed = urlparse(file_path)
                            path = parsed.path.lstrip("/")
                            self.logger.debug(f"parsed path: {path}")
                            # Extract the part after 'bot<token>/'
                            parts = path.split("/")
                            self.logger.debug(f"path parts: {parts}")
                            if len(parts) >= 2:
                                # Find the index of 'photos' or 'profile_photos'
                                for i, part in enumerate(parts):
                                    if part in ("photos", "profile_photos"):
                                        file_path = "/".join(parts[i:])
                                        self.logger.debug(
                                            f"extracted file_path: {file_path}"
                                        )
                                        break
                        self.logger.debug(f"final avatar URL: {host}/file/{file_path}")
                        user_avatar = f"{host}/file/{file_path}"
                    elif f.file_path:
                        # Fallback: use direct Telegram API URL
                        user_avatar = f.file_path
            except Exception as e:
                self.logger.warning(f"failed to fetch avatar for user {user_id}: {e}")

        attachments: list[Attachment] = []

        try:
            if msg.photo:
                largest = max(msg.photo, key=lambda p: p.file_size or 0)
                f = await largest.get_file()
                assert f.file_path is not None
                attachments.append(
                    Attachment(
                        type="image",
                        url=f.file_path,
                        name="photo.jpg",
                        size=largest.file_size or -1,
                    )
                )
            elif msg.video:
                f = await msg.video.get_file()
                assert f.file_path is not None
                attachments.append(
                    Attachment(
                        type="video",
                        url=f.file_path,
                        name=msg.video.file_name or "video.mp4",
                        size=msg.video.file_size or -1,
                    )
                )
            elif msg.voice:
                f = await msg.voice.get_file()
                assert f.file_path is not None
                attachments.append(
                    Attachment(
                        type="voice",
                        url=f.file_path,
                        name="voice.ogg",
                        size=msg.voice.file_size or -1,
                    )
                )
            elif msg.audio:
                f = await msg.audio.get_file()
                assert f.file_path is not None
                attachments.append(
                    Attachment(
                        type="voice",
                        url=f.file_path,
                        name=msg.audio.file_name or "audio.mp3",
                        size=msg.audio.file_size or -1,
                    )
                )
            elif msg.animation:
                f = await msg.animation.get_file()
                assert f.file_path is not None
                attachments.append(
                    Attachment(
                        type="video",
                        url=f.file_path,
                        name="animation.gif",
                        size=msg.animation.file_size or -1,
                    )
                )
            elif msg.sticker:
                if msg.sticker.is_animated or msg.sticker.is_video:
                    # animated/video stickers can't be sent as static images
                    if msg.sticker.emoji:
                        text = msg.sticker.emoji
                else:
                    try:
                        f = await msg.sticker.get_file()
                        assert f.file_path is not None
                        attachments.append(
                            Attachment(
                                type="image",
                                url=f.file_path,
                                name="sticker.webp",
                                size=msg.sticker.file_size or -1,
                            )
                        )
                    except Exception as e:
                        self.logger.warning(
                            f"failed to fetch sticker, falling back to emoji: {e}"
                        )
                        if msg.sticker.emoji:
                            text = msg.sticker.emoji
            elif msg.document:
                f = await msg.document.get_file()
                assert f.file_path is not None
                attachments.append(
                    Attachment(
                        type="file",
                        url=f.file_path,
                        name=msg.document.file_name or "document",
                        size=msg.document.file_size or -1,
                    )
                )
        except Exception as e:
            self.logger.error(f"failed to resolve file: {e}")

        if not text.strip() and not attachments:
            return

        normalized = NormalizedMessage(
            platform="telegram",
            instance_id=self.instance_id,
            channel={"chat_id": chat_id},
            nickname=nickname,
            user_id=user_id,
            user_avatar=user_avatar,
            text=text,
            attachments=attachments,
            message_id=str(msg.message_id),
            reply_parent=str(msg.reply_to_message.message_id)
            if msg.reply_to_message
            else None,
            mentions=mentions,
            time=msg.date.isoformat() if msg.date else None,
            source_proxy=self._media_proxy,
            username=username,
            is_dm=msg.chat_id > 0,
        )
        await self.bridge.on_message(normalized)

    async def _on_edited_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        msg = update.edited_message
        if not msg:
            return
        text = msg.text or msg.caption or ""
        if not text.strip():
            return
        chat_id = str(msg.chat_id)
        from_user = msg.from_user
        user_id = str(from_user.id) if from_user else ""
        nickname = (
            (from_user.full_name or from_user.username or user_id)
            if from_user
            else user_id
        )
        username = from_user.username or "" if from_user else ""
        normalized = NormalizedMessage(
            platform="telegram",
            instance_id=self.instance_id,
            channel={"chat_id": chat_id},
            nickname=nickname,
            user_id=user_id,
            text=text,
            message_id=str(msg.message_id),
            edit_target_id=str(msg.message_id),
            is_edit=True,
            time=msg.edit_date.isoformat() if msg.edit_date else None,
            source_proxy=self._media_proxy,
            username=username,
            is_dm=msg.chat_id > 0,
        )
        await self.bridge.on_edit_message(normalized)

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
            self.logger.warning(f"send: no chat_id in channel {channel}")
            return
        if self._app is None:
            self.logger.warning("send: driver not started")
            return

        cid = int(chat_id)

        caption_used = False

        parse_mode: str | None = None
        link_preview_opts: LinkPreviewOptions | None = None

        reply_to_id = kwargs.get("reply_to_id")
        reply_params = None
        if reply_to_id:
            try:
                reply_params = ReplyParameters(message_id=int(reply_to_id))
            except (ValueError, TypeError):
                pass

        msg_ids = []

        rich_header = kwargs.get("rich_header")
        if rich_header:
            host = self.config.rich_header_host.rstrip("/")
            has_attachments = bool(attachments)

            if host and not has_attachments:
                # Preferred path: Cloudflare Worker returns an OG page; Telegram
                # shows it as a small avatar+name card above the message text.
                params: dict = {
                    "title": rich_header.get("title", ""),
                    "content": rich_header.get("content", ""),
                }
                if av := rich_header.get("avatar", ""):
                    params["avatar"] = av
                rh_url = f"{host}/richheader?{urlencode(params)}"
                link_preview_opts = LinkPreviewOptions(
                    url=rh_url,
                    prefer_small_media=True,
                    show_above_text=True,
                )
            else:
                # Fallback: embed the header as HTML bold text (used when
                # rich_header_host is not configured or when there are media
                # attachments, since captions cannot carry link previews).
                header = telegram_richheader_html(
                    rich_header.get("title", ""),
                    rich_header.get("content", ""),
                )
                body = html.escape(text) if text else ""
                text = f"{header}\n{body}" if body else header
                parse_mode = "HTML"

        # Handle mentions
        mentions = kwargs.get("mentions", [])
        if mentions:
            # If parse_mode is not yet HTML, we need to escape existing text and switch to HTML
            if parse_mode != "HTML":
                text = html.escape(text)
                parse_mode = "HTML"

            for m in mentions:
                # Telegram mention: <a href="tg://user?id=123456">Name</a>
                # Assuming m['id'] is numeric ID. If it's @username, we just keep @username
                if m["id"].isdigit():
                    link = (
                        f'<a href="tg://user?id={m["id"]}">{html.escape(m["name"])}</a>'
                    )
                    text = text.replace(f"@{html.escape(m['name'])}", link)

        if self.config.sanitize_accidental_mentions:
            text = re.sub(r"(^|\s)@([A-Za-z0-9_]+)", r"\1@" + "\u200b" + r"\2", text)

        source_proxy = self._source_proxy_from_kwargs(kwargs)
        try:
            for att in attachments or []:
                if not att.url and att.data is None:
                    continue

                result = await media.fetch_attachment(
                    att, self.config.max_file_size, source_proxy
                )
                if not result:
                    # Oversized or failed — append as text (escape if in HTML mode)
                    label = att.name or att.url or ""
                    text += _attachment_fallback_label(att.type, label, parse_mode)
                    continue

                data_bytes, mime = result
                fname = media.filename_for(att.name, mime)

                if att.type == "image":
                    data_bytes, fname = _prepare_photo_for_telegram(
                        data_bytes,
                        fname,
                        self.config.photo_padding_color,
                    )
                    if data_bytes is None:
                        label = att.name or att.url or fname
                        text += _attachment_fallback_label("image", label, parse_mode)
                        continue

                # validate photo data
                if not data_bytes or len(data_bytes) == 0:
                    self.logger.warning(f"Empty image data for {fname}, skipping")
                    label = att.name or att.url or ""
                    text += _attachment_fallback_label(att.type, label, parse_mode)
                    continue

                bio = io.BytesIO(data_bytes)
                bio.name = fname
                caption = text if not caption_used else None

                try:
                    match att.type:
                        case "image":
                            sent = await self._app.bot.send_photo(
                                chat_id=cid,
                                photo=bio,
                                caption=caption,
                                parse_mode=parse_mode,
                                reply_parameters=reply_params,
                            )
                        case "voice":
                            sent = await self._app.bot.send_voice(
                                chat_id=cid,
                                voice=bio,
                                caption=caption,
                                parse_mode=parse_mode,
                                reply_parameters=reply_params,
                            )
                        case "video":
                            sent = await self._app.bot.send_video(
                                chat_id=cid,
                                video=bio,
                                caption=caption,
                                parse_mode=parse_mode,
                                reply_parameters=reply_params,
                            )
                        case _:
                            sent = await self._app.bot.send_document(
                                chat_id=cid,
                                document=bio,
                                caption=caption,
                                parse_mode=parse_mode,
                                reply_parameters=reply_params,
                            )

                    if sent and sent.message_id:
                        msg_ids.append(str(sent.message_id))
                    caption_used = True
                except Exception as e:
                    label = att.name or att.url or fname
                    text += _attachment_fallback_label(att.type, label, parse_mode)
                    self.logger.warning(f"attachment send failed ({att.type}): {e}")
                    continue

            # Send text-only if no attachments consumed it
            if text and not caption_used:
                sent = await self._app.bot.send_message(
                    chat_id=cid,
                    text=log.replace_sensitive(text),
                    parse_mode=parse_mode,
                    link_preview_options=link_preview_opts,
                    reply_parameters=reply_params,
                )
                if sent and sent.message_id:
                    msg_ids.append(str(sent.message_id))

            return msg_ids if msg_ids else None

        except Exception as e:
            self.logger.error(f"send failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Edit
    # ------------------------------------------------------------------

    async def edit(self, channel: dict, message_id: str, text: str, **kwargs):
        """Edit a previously sent message by ID."""
        chat_id = channel.get("chat_id")
        if not chat_id or self._app is None:
            return
        parse_mode: str | None = None
        link_preview_opts: LinkPreviewOptions | None = None
        rich_header = kwargs.get("rich_header")
        if rich_header:
            host = self.config.rich_header_host.rstrip("/")
            if host:
                params: dict = {
                    "title": rich_header.get("title", ""),
                    "content": rich_header.get("content", ""),
                }
                if av := rich_header.get("avatar", ""):
                    params["avatar"] = av
                from urllib.parse import urlencode

                rh_url = f"{host}/richheader?{urlencode(params)}"
                link_preview_opts = LinkPreviewOptions(
                    url=rh_url,
                    prefer_small_media=True,
                    show_above_text=True,
                )
            else:
                header = telegram_richheader_html(
                    rich_header.get("title", ""),
                    rich_header.get("content", ""),
                )
                body = html.escape(text) if text else ""
                text = f"{header}\n{body}" if body else header
                parse_mode = "HTML"
        try:
            await self._app.bot.edit_message_text(
                chat_id=int(chat_id),
                message_id=int(message_id),
                text=log.replace_sensitive(text),
                parse_mode=parse_mode,
                link_preview_options=link_preview_opts,
            )
        except Exception as e:
            self.logger.warning(f"edit failed for message {message_id}: {e}")

    # ------------------------------------------------------------------
    # Delete / recall
    # ------------------------------------------------------------------

    async def delete(self, channel: dict, message_id: str, **kwargs):
        """Delete (recall) a previously sent message by ID.

        Note: the Telegram Bot API provides no update when a user deletes a
        message, so a recall can be *applied* to Telegram but never *detected*
        from a Telegram source.
        """
        if not self.config.enable_recall:
            return
        chat_id = channel.get("chat_id")
        if not chat_id or self._app is None or not message_id:
            return
        try:
            await self._app.bot.delete_message(
                chat_id=int(chat_id),
                message_id=int(message_id),
            )
        except Exception as e:
            self.logger.warning(f"delete failed for message {message_id}: {e}")


register("telegram", TelegramConfig, TelegramDriver)
