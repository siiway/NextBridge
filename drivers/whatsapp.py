# WhatsApp driver via neonize (Python bindings for go-whatsapp / whatsmeow).
# No Node.js required.
#
# Config keys (under whatsapp.<instance_id>):
#   storage_dir  – Path to the SQLite auth DB (default ~/.nextbridge/whatsapp/<instance_id>.db)
#
# Rule channel keys:
#   chat_id  – WhatsApp JID string, e.g. "1234567890@s.whatsapp.net" or "123456789@g.us"
#
# Setup:
#   uv add neonize
#   On first run a QR code is printed to the terminal — scan it with WhatsApp (Linked Devices).
#
# Platform-specific dependencies:
#   - Linux (Ubuntu/Debian): sudo apt install libmagic1
#   - Linux (Fedora/RHEL): sudo dnf install file-libs
#   - macOS: brew install libmagic
#   - Windows: python-magic-bin is installed automatically

from __future__ import annotations

import asyncio
from pathlib import Path

from neonize.aioze.client import NewAClient
from neonize.aioze.events import (
    ConnectedEv,
    DisconnectedEv,
    MessageEv,
    PairStatusEv,
    QREv,
)
from neonize.utils.jid import Jid2String, build_jid

from drivers import BaseDriver
from drivers.registry import register
import services.logger as log
from services.message import Attachment, NormalizedMessage
from services.config_schema import _DriverConfig


class WhatsAppConfig(_DriverConfig):
    storage_dir: str = ""  # defaults to ~/.nextbridge/whatsapp/<instance_id>.db


logger = log.get_logger()


class WhatsAppDriver(BaseDriver[WhatsAppConfig]):
    def __init__(self, instance_id: str, config: WhatsAppConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._client: NewAClient | None = None

    async def start(self):
        self.bridge.register_sender(self.instance_id, self.send)

        db_path = self.config.storage_dir or str(
            Path.home() / ".nextbridge" / "whatsapp" / f"{self.instance_id}.db"
        )
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        client = NewAClient(db_path)
        self._client = client

        @client.event(ConnectedEv)
        async def on_connected(_c: NewAClient, _e: ConnectedEv) -> None:
            logger.info(f"WhatsApp [{self.instance_id}] connected")

        @client.event(DisconnectedEv)
        async def on_disconnected(_c: NewAClient, _e: DisconnectedEv) -> None:
            logger.warning(f"WhatsApp [{self.instance_id}] disconnected")

        @client.event(QREv)
        async def on_qr(_c: NewAClient, _e: QREv) -> None:
            logger.info(
                f"WhatsApp [{self.instance_id}] QR code displayed — scan it in the terminal"
            )

        @client.event(PairStatusEv)
        async def on_pair(_c: NewAClient, evt: PairStatusEv) -> None:
            logger.info(f"WhatsApp [{self.instance_id}] logged in as {evt.ID.User}")

        @client.event(MessageEv)
        async def on_message(_c: NewAClient, evt: MessageEv) -> None:
            try:
                await self._handle(evt)
            except Exception as e:
                logger.error(
                    f"WhatsApp [{self.instance_id}] message handler error: {e}"
                )

        try:
            await client.connect()
            await client.idle()
        except asyncio.CancelledError:
            pass

    async def _handle(self, evt: MessageEv) -> None:
        src = evt.Info.MessageSource
        if src.IsFromMe:
            return

        chat = src.Chat
        chat_str = Jid2String(chat)

        # Skip WhatsApp status broadcast
        if chat_str == "status@broadcast" or chat.Server == "broadcast":
            return

        sender = src.Sender
        user = sender.User or chat.User
        msg_id = evt.Info.ID
        timestamp = evt.Info.Timestamp

        m = evt.Message
        text: str = ""
        attachments: list[Attachment] = []

        if m.HasField("conversation"):
            text = m.conversation
        elif m.HasField("extendedTextMessage"):
            text = m.extendedTextMessage.text
        elif m.HasField("imageMessage"):
            text = m.imageMessage.caption or ""
            attachments.append(Attachment(type="image", url="", name="image.jpg"))
        elif m.HasField("videoMessage"):
            text = m.videoMessage.caption or ""
            attachments.append(Attachment(type="video", url="", name="video.mp4"))
        elif m.HasField("audioMessage"):
            text = "[Voice Message]"
            attachments.append(Attachment(type="voice", url="", name="audio.ogg"))
        elif m.HasField("documentMessage"):
            text = m.documentMessage.caption or ""
            fname = m.documentMessage.fileName or "document"
            attachments.append(Attachment(type="file", url="", name=fname))
        else:
            return

        if not text.strip() and not attachments:
            return

        normalized = NormalizedMessage(
            platform="whatsapp",
            instance_id=self.instance_id,
            channel={"chat_id": chat_str},
            nickname=user,
            user_id=user,
            user_avatar="",
            text=text,
            attachments=attachments,
            message_id=msg_id or None,
            time=str(timestamp) if timestamp else None,
        )
        await self.bridge.on_message(normalized)

    async def send(
        self,
        channel: dict,
        text: str,
        attachments: list[Attachment] | None = None,
        **kwargs,
    ) -> str | None:
        chat_id = channel.get("chat_id")
        if not chat_id or not self._client:
            logger.warning(f"WhatsApp [{self.instance_id}] send: not ready")
            return None

        user, server = (
            chat_id.split("@", 1) if "@" in chat_id else (chat_id, "s.whatsapp.net")
        )
        jid = build_jid(user, server)

        body = text or ""
        if attachments:
            for att in attachments:
                label = att.name or att.url or ""
                body += f"\n[{att.type.capitalize()}: {label}]"

        try:
            result = await self._client.send_message(jid, body)
            return result.ID if result else None
        except Exception as e:
            logger.error(f"WhatsApp [{self.instance_id}] send failed: {e}")
            return None


register("whatsapp", WhatsAppConfig, WhatsAppDriver)
