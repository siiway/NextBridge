# KOOK (开黑啦) driver via khl-py (WebSocket mode).
#
# Receive: khl.Bot connects to KOOK via WebSocket; TEXT and KMD messages from
#          public text channels are forwarded to the bridge.
# Send:    Fetch the target channel then call channel.send().
#          Images are uploaded to KOOK CDN via client.create_asset() and
#          embedded with KMarkdown (img) syntax.
#          Other attachment types are uploaded and sent as hyperlinks.
#
# Config keys (under kook.<instance_id>):
#   token         – KOOK bot token (required)
#   max_file_size – Max bytes per attachment when uploading (default 25 MB)
#
# Rule channel keys:
#   channel_id – KOOK text channel ID

from drivers.registry import register
import io
import re

import khl

import services.logger as log
import services.media as media
from services.message import Attachment, NormalizedMessage
from services.config_schema import _DriverConfig
from services.db import msg_db
from drivers import BaseDriver


class KookConfig(_DriverConfig):
    token: str
    max_file_size: int = 25 * 1024 * 1024


logger = log.get_logger()


class KookDriver(BaseDriver[KookConfig]):
    def __init__(self, instance_id: str, config: KookConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._bot: khl.Bot | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self.bridge.register_sender(self.instance_id, self.send)

        self._bot = khl.Bot(token=self.config.token)

        # Register our handler alongside khl's internal command-manager handler.
        # khl's Client dispatches to all registered handlers for a given type.
        async def on_msg(msg: khl.Message):
            if not isinstance(msg, khl.PublicMessage):
                return
            await self._on_message(msg)

        self._bot.client.register(khl.MessageTypes.TEXT, on_msg)
        self._bot.client.register(khl.MessageTypes.KMD, on_msg)

        logger.info(f"Kook [{self.instance_id}] starting WebSocket connection")
        await self._bot.start()

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def _on_message(self, msg: khl.PublicMessage):
        channel_id = msg.channel.id
        author = msg.author  # GuildUser
        user_id = str(author.id)
        # Prefer the per-guild nickname over the global username
        username = author.nickname or author.username or user_id
        avatar = author.avatar or ""
        text = msg.content or ""

        if not text.strip():
            return

        mentions = []
        # Parse (met)userId(met) or (met)all(met)
        # We ignore (met)all(met) for now as it doesn't map to a single user
        met_matches = re.finditer(r"\(met\)(\d+)\(met\)", text)
        for match in met_matches:
            uid = match.group(1)
            # Try to get display name from cache/DB if we've seen them before
            name = msg_db.get_user_name(self.instance_id, uid)
            if not name:
                # If unknown, we can't easily fetch it without an extra API call
                # Fallback to ID or generic placeholder
                name = uid

            text = text.replace(match.group(0), f"@{name}")
            mentions.append({"id": uid, "name": name})

        normalized = NormalizedMessage(
            platform="kook",
            instance_id=self.instance_id,
            channel={"channel_id": channel_id},
            user=username,
            user_id=user_id,
            user_avatar=avatar,
            text=text,
            attachments=[],
            mentions=mentions,
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
        reply_to_id = kwargs.get("reply_to_id")

        if self._bot is None:
            logger.warning(
                f"Kook [{self.instance_id}] send: driver not started")
            return

        channel_id = channel.get("channel_id")
        if not channel_id:
            logger.warning(
                f"Kook [{self.instance_id}] send: no channel_id in channel {channel}"
            )
            return

        rich_header = kwargs.get("rich_header")
        if rich_header:
            t, c = rich_header.get("title", ""), rich_header.get("content", "")
            # KOOK uses KMarkdown — same bold/italic syntax as Discord Markdown
            prefix = f"**{t}**" + (f" · *{c}*" if c else "")
            text = f"{prefix}\n{text}" if text else prefix

        has_mention = False
        mentions = kwargs.get("mentions", [])
        for m in mentions:
            if f"@{m['name']}" in text:
                text = text.replace(f"@{m['name']}", f"(met){m['id']}(met)")
                has_mention = True

        has_image = False
        attachment_fragments: list[str] = []

        for att in attachments or []:
            if not att.url and att.data is None:
                continue

            result = await media.fetch_attachment(att, self.config.max_file_size)
            if not result:
                label = att.name or att.url or ""
                attachment_fragments.append(
                    f"\n[{att.type.capitalize()}: {label}]")
                continue

            data_bytes, mime = result
            fname = media.filename_for(att.name, mime)

            try:
                asset_url = await self._bot.client.create_asset(io.BytesIO(data_bytes))
            except Exception as e:
                logger.error(
                    f"Kook [{self.instance_id}] asset upload failed: {e}")
                label = att.name or att.url or fname
                attachment_fragments.append(
                    f"\n[{att.type.capitalize()}: {label}]")
                continue

            if att.type == "image":
                # KMarkdown inline image syntax
                attachment_fragments.append(f"\n(img){asset_url}(img)")
                has_image = True
            else:
                attachment_fragments.append(f"\n[{fname}]({asset_url})")

        full_text = (text or "") + "".join(attachment_fragments)
        if not full_text.strip():
            return

        # Use KMD type when the message contains KMarkdown image syntax or
        # the rich header uses bold/italic or has mentions; TEXT otherwise.
        msg_type = (
            khl.MessageTypes.KMD
            if (has_image or rich_header or has_mention)
            else khl.MessageTypes.TEXT
        )

        try:
            ch = await self._bot.client.fetch_public_channel(channel_id)
            if reply_to_id:
                await ch.send(full_text, type=msg_type, quote=reply_to_id)
            else:
                await ch.send(full_text, type=msg_type)
        except Exception as e:
            logger.error(f"Kook [{self.instance_id}] send failed: {e}")


register("kook", KookConfig, KookDriver)
