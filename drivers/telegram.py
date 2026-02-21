# Telegram driver via python-telegram-bot (v20+).
# Uses long-polling to receive messages and the bot API to send.
#
# Config keys (under telegram.<instance_id>):
#   bot_token         – Telegram bot token from @BotFather (required)
#   max_file_size     – Max bytes per attachment when sending (default 50 MB,
#                       Telegram bot API limit)
#   rich_header_host  – Base URL of the Cloudflare rich-header worker
#                       (e.g. "https://richheader.yourname.workers.dev").
#                       When set, text-only bridged messages whose msg_format
#                       includes a <richheader/> tag are sent with a small OG
#                       link-preview card shown above the text (avatar + name).
#                       Falls back to bold HTML header when absent or when the
#                       message carries media attachments.
#
# Rule channel keys:
#   chat_id – Telegram chat ID (negative for groups, e.g. "-100123456789")

import asyncio
import html
import io
from urllib.parse import urlencode

from telegram import LinkPreviewOptions, Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

import services.logger as log
import services.media as media
from services.message import Attachment, NormalizedMessage
from services.config_schema import _DriverConfig
from drivers import BaseDriver


class TelegramConfig(_DriverConfig):
    bot_token:        str
    max_file_size:    int = 50 * 1024 * 1024
    rich_header_host: str = ""

l = log.get_logger()

# Catch all non-command message types that may carry content
def _richheader_html(title: str, content: str) -> str:
    """Render a rich header as a Telegram HTML snippet."""
    t = html.escape(title)
    c = html.escape(content)
    return f"<b>{t}</b>" + (f" · <i>{c}</i>" if c else "")


_CONTENT_FILTER = (
    filters.TEXT
    | filters.PHOTO
    | filters.VIDEO
    | filters.VOICE
    | filters.AUDIO
    | filters.Document.ALL
    | filters.ANIMATION
) & ~filters.COMMAND


class TelegramDriver(BaseDriver[TelegramConfig]):

    def __init__(self, instance_id: str, config: TelegramConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._app: Application | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self.bridge.register_sender(self.instance_id, self.send)

        self._app = Application.builder().token(self.config.bot_token).build()
        self._app.add_handler(MessageHandler(_CONTENT_FILTER, self._on_message))

        # async-with handles initialize() / shutdown() automatically
        async with self._app:
            await self._app.start()
            await self._app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            l.info(f"Telegram [{self.instance_id}] polling started")
            try:
                await asyncio.Event().wait()  # keep running until cancelled
            finally:
                await self._app.updater.stop()
                await self._app.stop()

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg:
            return

        # Media messages use caption instead of text
        text = msg.text or msg.caption or ""

        chat_id = str(msg.chat_id)
        from_user = msg.from_user
        user_id = str(from_user.id) if from_user else ""
        user_name = (
            (from_user.full_name or from_user.username or user_id)
            if from_user
            else user_id
        )

        attachments: list[Attachment] = []

        try:
            if msg.photo:
                largest = max(msg.photo, key=lambda p: p.file_size or 0)
                f = await largest.get_file()
                attachments.append(
                    Attachment(type="image", url=f.file_path, name="photo.jpg",
                               size=largest.file_size or -1)
                )
            elif msg.video:
                f = await msg.video.get_file()
                attachments.append(
                    Attachment(type="video", url=f.file_path,
                               name=msg.video.file_name or "video.mp4",
                               size=msg.video.file_size or -1)
                )
            elif msg.voice:
                f = await msg.voice.get_file()
                attachments.append(
                    Attachment(type="voice", url=f.file_path, name="voice.ogg",
                               size=msg.voice.file_size or -1)
                )
            elif msg.audio:
                f = await msg.audio.get_file()
                attachments.append(
                    Attachment(type="voice", url=f.file_path,
                               name=msg.audio.file_name or "audio.mp3",
                               size=msg.audio.file_size or -1)
                )
            elif msg.animation:
                f = await msg.animation.get_file()
                attachments.append(
                    Attachment(type="video", url=f.file_path, name="animation.gif",
                               size=msg.animation.file_size or -1)
                )
            elif msg.document:
                f = await msg.document.get_file()
                attachments.append(
                    Attachment(type="file", url=f.file_path,
                               name=msg.document.file_name or "document",
                               size=msg.document.file_size or -1)
                )
        except Exception as e:
            l.error(f"Telegram [{self.instance_id}] failed to resolve file: {e}")

        if not text.strip() and not attachments:
            return

        normalized = NormalizedMessage(
            platform="telegram",
            instance_id=self.instance_id,
            channel={"chat_id": chat_id},
            user=user_name,
            user_id=user_id,
            user_avatar="",  # Telegram avatar requires an extra API call
            text=text,
            attachments=attachments,
        )
        await self.bridge.on_message(normalized)

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
            l.warning(f"Telegram [{self.instance_id}] send: no chat_id in channel {channel}")
            return
        if self._app is None:
            l.warning(f"Telegram [{self.instance_id}] send: driver not started")
            return

        cid = int(chat_id)
        max_size: int = self.config.max_file_size
        caption_used = False

        parse_mode: str | None = None
        link_preview_opts: LinkPreviewOptions | None = None

        rich_header = kwargs.get("rich_header")
        if rich_header:
            host = self.config.rich_header_host.rstrip("/")
            has_attachments = bool(attachments)

            if host and not has_attachments:
                # Preferred path: Cloudflare Worker returns an OG page; Telegram
                # shows it as a small avatar+name card above the message text.
                params: dict = {
                    "title":   rich_header.get("title", ""),
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
                header = _richheader_html(
                    rich_header.get("title", ""),
                    rich_header.get("content", ""),
                )
                body = html.escape(text) if text else ""
                text = f"{header}\n{body}" if body else header
                parse_mode = "HTML"

        try:
            for att in (attachments or []):
                if not att.url and att.data is None:
                    continue

                result = await media.fetch_attachment(att, max_size)
                if not result:
                    # Oversized or failed — append as text (escape if in HTML mode)
                    label = att.name or att.url or ""
                    if parse_mode == "HTML":
                        label = html.escape(label)
                    text += f"\n[{att.type.capitalize()}: {label}]"
                    continue

                data_bytes, mime = result
                fname = media.filename_for(att.name, mime)
                bio = io.BytesIO(data_bytes)
                bio.name = fname
                caption = text if not caption_used else None

                if att.type == "image":
                    await self._app.bot.send_photo(
                        chat_id=cid, photo=bio, caption=caption, parse_mode=parse_mode
                    )
                elif att.type == "voice":
                    await self._app.bot.send_voice(
                        chat_id=cid, voice=bio, caption=caption, parse_mode=parse_mode
                    )
                elif att.type == "video":
                    await self._app.bot.send_video(
                        chat_id=cid, video=bio, caption=caption, parse_mode=parse_mode
                    )
                else:
                    await self._app.bot.send_document(
                        chat_id=cid, document=bio, caption=caption, parse_mode=parse_mode
                    )

                caption_used = True

            # Send text-only if no attachments consumed it
            if text and not caption_used:
                await self._app.bot.send_message(
                    chat_id=cid,
                    text=text,
                    parse_mode=parse_mode,
                    link_preview_options=link_preview_opts,
                )

        except Exception as e:
            l.error(f"Telegram [{self.instance_id}] send failed: {e}")


from drivers.registry import register
register("telegram", TelegramConfig, TelegramDriver)
