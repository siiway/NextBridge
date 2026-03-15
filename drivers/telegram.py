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
#
# Rule channel keys:
#   chat_id – Telegram chat ID (negative for groups, e.g. "-100123456789")

from drivers.registry import register
import asyncio
import html
import io
from urllib.parse import urlencode

from telegram import LinkPreviewOptions, ReplyParameters, Update
from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

from drivers import BaseDriver
import services.logger as log
import services.media as media
from services.message import Attachment, NormalizedMessage
from services.config_schema import _DriverConfig
from services.config import get


class TelegramConfig(_DriverConfig):
    bot_token: str
    max_file_size: int = 50 * 1024 * 1024
    rich_header_host: str = ""
    proxy: str = ""


logger = log.get_logger()


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
        self._proxy: str | None = config.proxy or get("global.proxy", "") or None  # type: ignore

    async def start(self):
        self.bridge.register_sender(self.instance_id, self.send)
        # https://github.com/HKUDS/nanobot/blob/58389766a7ab307c7d5a31a1df36d1cacc625054/{file}#L143
        req = HTTPXRequest(
            pool_timeout=5.0,
            connect_timeout=30.0,
            read_timeout=30.0,
            write_timeout=30.0,
            media_write_timeout=30.0,
            proxy=self._proxy,
        )
        self._app = (
            Application.builder()
            .token(self.config.bot_token)
            .request(req)
            .get_updates_request(req)
            .build()
        )
        self._app.add_handler(MessageHandler(_CONTENT_FILTER, self._on_message))
        self._app.add_error_handler(self._on_error)

        logger.info(f"Telegram [{self.instance_id}] starting application and polling.")

        # ensure bot's get_me is retried on failure
        # error in start/start_polling shouldn't happen, so let it crash if it does
        try:
            while True:
                try:
                    await self._app.initialize()
                    break
                except TelegramError as e:
                    logger.error(
                        f"Telegram [{self.instance_id}] initialization failed: {e}, retrying in 5 seconds..."
                    )
                    await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info(f"Telegram [{self.instance_id}] initialization cancelled.")
            return
        await self._app.start()
        assert self._app.updater is not None
        logger.info(f"Telegram [{self.instance_id}] application started.")
        await self._app.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            timeout=10,
            bootstrap_retries=10,
        )
        logger.info(f"Telegram [{self.instance_id}] polling started.")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            logger.info(f"Telegram [{self.instance_id}] polling cancelled.")
        finally:
            await self.stop()

    async def stop(self):
        if not self._app:
            return None
        if self._app.updater and self._app.updater.running:
            await self._app.updater.stop()
        if self._app.running:
            await self._app.stop()
        if not self._app.running:
            await self._app.shutdown()
        self._app = None

    async def _on_error(self, _: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.exception(
            "Telegram [%s] handler error", self.instance_id, exc_info=context.error
        )

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg:
            return

        # Media messages use caption instead of text
        text = msg.text or msg.caption or ""

        mentions = []
        entities = msg.entities or msg.caption_entities or []
        for ent in entities:
            if ent.type == "mention":
                # @username mention
                # Extract username from text
                offset = ent.offset
                length = ent.length
                username = text[offset : offset + length]  # includes @
                # We don't have ID for @username mentions easily unless we resolve it
                # But we can store it as name=username
                mentions.append({"id": username, "name": username[1:]})
            elif ent.type == "text_mention":
                # Text link to user
                user = ent.user
                if user:
                    uid = str(user.id)
                    name = user.full_name or user.username or uid
                    mentions.append({"id": uid, "name": name})

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
            logger.error(f"Telegram [{self.instance_id}] failed to resolve file: {e}")

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
            message_id=str(msg.message_id),
            reply_parent=str(msg.reply_to_message.message_id)
            if msg.reply_to_message
            else None,
            mentions=mentions,
            time=msg.date.isoformat() if msg.date else None,
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
            logger.warning(
                f"Telegram [{self.instance_id}] send: no chat_id in channel {channel}"
            )
            return
        if self._app is None:
            logger.warning(f"Telegram [{self.instance_id}] send: driver not started")
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

        first_msg_id = None

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
                header = _richheader_html(
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

        try:
            for att in attachments or []:
                if not att.url and att.data is None:
                    continue

                result = await media.fetch_attachment(
                    att, self.config.max_file_size, self._proxy
                )
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
                    sent = await self._app.bot.send_photo(
                        chat_id=cid,
                        photo=bio,
                        caption=caption,
                        parse_mode=parse_mode,
                        reply_parameters=reply_params,
                    )
                    if not first_msg_id:
                        first_msg_id = str(sent.message_id)
                elif att.type == "voice":
                    sent = await self._app.bot.send_voice(
                        chat_id=cid,
                        voice=bio,
                        caption=caption,
                        parse_mode=parse_mode,
                        reply_parameters=reply_params,
                    )
                    if not first_msg_id:
                        first_msg_id = str(sent.message_id)
                elif att.type == "video":
                    sent = await self._app.bot.send_video(
                        chat_id=cid,
                        video=bio,
                        caption=caption,
                        parse_mode=parse_mode,
                        reply_parameters=reply_params,
                    )
                    if not first_msg_id:
                        first_msg_id = str(sent.message_id)
                else:
                    sent = await self._app.bot.send_document(
                        chat_id=cid,
                        document=bio,
                        caption=caption,
                        parse_mode=parse_mode,
                        reply_parameters=reply_params,
                    )
                    if not first_msg_id:
                        first_msg_id = str(sent.message_id)

                caption_used = True

            # Send text-only if no attachments consumed it
            if text and not caption_used:
                sent = await self._app.bot.send_message(
                    chat_id=cid,
                    text=log.replace_sensitive(text),
                    parse_mode=parse_mode,
                    link_preview_options=link_preview_opts,
                    reply_parameters=reply_params,
                )
                if not first_msg_id:
                    first_msg_id = str(sent.message_id)

            return first_msg_id

        except Exception as e:
            logger.error(f"Telegram [{self.instance_id}] send failed: {e}")
            return None


register("telegram", TelegramConfig, TelegramDriver)
