# Matrix driver via mautrix.
#
# Receive: Client.start() sync loop.  ROOM_MESSAGE events (text and media)
#          are forwarded to the bridge.  Media is downloaded eagerly via
#          the authenticated client so downstream drivers do not need
#          Matrix credentials.
# Send:    send_text() for text; upload_media() + send_file() for media.
#
# Config keys (under matrix.<instance_id>):
#   homeserver    – Homeserver URL, e.g. "https://matrix.org" (required)
#   user_id       – Full Matrix user ID, e.g. "@bot:matrix.org" (required)
#   password      – Login password (required unless access_token is set)
#   access_token  – Access token (alternative to password)
#   max_file_size – Max bytes per attachment (default 50 MB)
#   enable_e2e    – Enable end-to-end encryption support (default: False)
#   store_path    – Path to store encryption keys (required if enable_e2e is True)
#
# Rule channel keys:
#   room_id – Matrix room ID, e.g. "!abc123:matrix.org"

from drivers.registry import register
from mautrix.client import Client
from mautrix.client.syncer import EventHandler
from mautrix.types import (
    AudioInfo,
    ContentURI,
    EventType,
    FileInfo,
    ImageInfo,
    InReplyTo,
    LoginType,
    MediaMessageEventContent,
    MessageEvent,
    MessageType,
    RelatesTo,
    RoomID,
    TextMessageEventContent,
    UserID,
    VideoInfo,
)
from mautrix.api import HTTPAPI
from mautrix.crypto import OlmMachine
from typing import cast
from aiohttp import ClientSession, TCPConnector
from aiohttp_socks import ProxyConnector
from pathlib import Path

from pydantic import model_validator

import services.logger as log
import services.media as media
from services.message import Attachment, NormalizedMessage
from services.config_schema import _DriverConfig
from services.config import get_proxy, UNSET
from drivers import BaseDriver


class MatrixConfig(_DriverConfig):
    homeserver: str
    user_id: str
    password: str = ""
    access_token: str = ""
    max_file_size: int = 10 * 1024 * 1024
    proxy: str | None = UNSET
    enable_e2e: bool = False
    store_path: str = "data/e2e"
    connect_timeout: int = 30

    @model_validator(mode="after")
    def _require_auth(self) -> "MatrixConfig":
        if not self.password and not self.access_token:
            raise ValueError("requires 'password' or 'access_token'")
        return self

    @model_validator(mode="after")
    def _require_e2e_store_path(self) -> "MatrixConfig":
        if self.enable_e2e and not self.store_path:
            raise ValueError("store_path is required when enable_e2e is True")
        return self


logger = log.get_logger()

_FILE_TYPES = {
    "image": MessageType.IMAGE,
    "video": MessageType.VIDEO,
    "voice": MessageType.AUDIO,
    "file": MessageType.FILE,
}


def _make_info(
    att_type: str, mime: str, size: int
) -> FileInfo | ImageInfo | VideoInfo | AudioInfo:
    if att_type == "image":
        return ImageInfo(mimetype=mime, size=size)
    if att_type == "video":
        return VideoInfo(mimetype=mime, size=size)
    if att_type == "voice":
        return AudioInfo(mimetype=mime, size=size)
    return FileInfo(mimetype=mime, size=size)


class MatrixDriver(BaseDriver[MatrixConfig]):
    def __init__(self, instance_id: str, config: MatrixConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._client: Client | None = None
        self._crypto: OlmMachine | None = None
        self._proxy = get_proxy(config.proxy)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        homeserver = self.config.homeserver.rstrip("/")
        user_id = self.config.user_id

        # proxy support
        session: ClientSession | None = None
        if self._proxy:
            logger.debug(f"Matrix [{self.instance_id}] using proxy {self._proxy}")
            connector = ProxyConnector.from_url(self._proxy, rdns=True)
        else:
            connector = None

        session = ClientSession(connector=connector or TCPConnector(ssl=True))

        api = HTTPAPI(
            base_url=homeserver,
            token="",  # to be set after login
            client_session=session,
        )

        self._client = Client(mxid=UserID(user_id), base_url=homeserver, api=api)

        if self.config.access_token:
            self._client.api.token = self.config.access_token
        else:
            try:
                await self._client.login(
                    login_type=LoginType.PASSWORD,
                    identifier=UserID(user_id),
                    password=self.config.password,
                    store_access_token=True,
                )
            except Exception as e:
                logger.error(f"Matrix [{self.instance_id}] login failed: {e}")
                return

        # Initialize E2E encryption if enabled
        if self.config.enable_e2e:
            try:
                from contextlib import asynccontextmanager
                from mautrix.crypto import StateStore
                from mautrix.crypto.store import MemoryCryptoStore
                from mautrix.client.state_store import MemoryStateStore

                # Create a custom CryptoStore that overrides the transaction() method
                class CustomCryptoStore(MemoryCryptoStore):
                    @asynccontextmanager
                    async def transaction(self):
                        yield None

                # Create a custom StateStore that adds the find_shared_rooms method
                class CustomStateStore(MemoryStateStore):
                    async def find_shared_rooms(self, user_id):
                        # For now, return an empty list as we don't track shared rooms
                        return []

                logger.info(
                    f"Matrix [{self.instance_id}] Initializing E2E encryption..."
                )

                # Create store directory if it doesn't exist
                store_path = Path(self.config.store_path)
                store_path.mkdir(parents=True, exist_ok=True)
                logger.debug(
                    f"Matrix [{self.instance_id}] E2E store path: {store_path}"
                )

                # Initialize crypto store
                logger.debug(
                    f"Matrix [{self.instance_id}] Using in-memory crypto store"
                )
                self._crypto_store = CustomCryptoStore(
                    account_id=user_id,
                    pickle_key="nextbridge_e2e",
                )
                logger.debug(f"Matrix [{self.instance_id}] Crypto store initialized")

                # Try to delete old crypto store data to avoid corrupted sessions
                try:
                    await self._crypto_store.delete()
                    logger.debug(
                        f"Matrix [{self.instance_id}] Old crypto store data deleted"
                    )
                except Exception as e:
                    logger.debug(
                        f"Matrix [{self.instance_id}] No old crypto store data to delete: {e}"
                    )

                # Initialize state store
                logger.debug(f"Matrix [{self.instance_id}] Using in-memory state store")
                self._state_store = CustomStateStore()
                logger.debug(f"Matrix [{self.instance_id}] State store initialized")

                # Initialize Olm machine for E2E encryption
                logger.debug(f"Matrix [{self.instance_id}] Initializing Olm machine...")
                self._crypto = OlmMachine(
                    client=self._client,
                    crypto_store=self._crypto_store,
                    state_store=cast(StateStore, self._state_store),
                )
                await self._crypto.load()
                logger.debug(f"Matrix [{self.instance_id}] Olm machine initialized")

                # Set up state store and crypto on the client
                self._client.state_store = self._state_store
                self._client.crypto = self._crypto

                logger.info(f"Matrix [{self.instance_id}] E2E encryption enabled")
            except Exception as e:
                logger.opt(exception=True).error(
                    f"Matrix [{self.instance_id}] E2E initialization failed: {e}"
                )
                logger.warning(
                    f"Matrix [{self.instance_id}] continuing without E2E encryption"
                )
                self._crypto = None
                self._crypto_store = None
        else:
            logger.info(f"Matrix [{self.instance_id}] E2E encryption is disabled")

        # Skip the initial sync batch so historical messages are not bridged
        self._client.ignore_first_sync = True
        self._client.ignore_initial_sync = True

        self._client.add_event_handler(
            EventType.ROOM_MESSAGE, cast(EventHandler, self._on_message)
        )

        # Add event handler for encrypted events
        if self._crypto:
            self._client.add_event_handler(
                EventType.ROOM_ENCRYPTED, cast(EventHandler, self._on_encrypted_message)
            )
            # Add event handler for room key events (needed for E2E encryption)
            self._client.add_event_handler(
                EventType.TO_DEVICE_ENCRYPTED,
                cast(EventHandler, self._crypto.handle_to_device_event),
            )

        # Register only after the client is fully ready so send() is never
        # called while self._client is None (e.g. after a config error above).
        self.bridge.register_sender(self.instance_id, self.send)
        logger.info(f"Matrix [{self.instance_id}] starting sync")
        try:
            await self._client.start(filter_data=None)
        except Exception as e:
            logger.error(f"Matrix [{self.instance_id}] sync loop error: {e}")
            raise

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _mxc_to_http(self, mxc_uri: str) -> str:
        if not mxc_uri or not mxc_uri.startswith("mxc://"):
            return ""
        return f"{self.config.homeserver.rstrip('/')}/_matrix/media/v3/download/{mxc_uri[6:]}"

    def _mxid_local(self, user_id: str) -> str:
        return user_id.split(":")[0].lstrip("@") if ":" in user_id else user_id

    async def _get_profile(self, user_id: str) -> tuple[str, str]:
        """Return (display_name, avatar_http_url) for a Matrix user ID."""
        display_name = self._mxid_local(user_id)
        avatar_url = ""
        if self._client is None:
            return display_name, avatar_url
        try:
            name = await self._client.get_displayname(UserID(user_id))
            if name:
                display_name = name
        except Exception:
            pass
        try:
            mxc = await self._client.get_avatar_url(UserID(user_id))
            if mxc:
                avatar_url = self._mxc_to_http(str(mxc))
        except Exception:
            pass
        return display_name, avatar_url

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def _on_encrypted_message(self, event) -> None:
        """Handle encrypted messages by decrypting them and processing the content."""
        if not self._crypto:
            logger.warning(
                f"Matrix [{self.instance_id}] Received encrypted message but E2E is not initialized"
            )
            return

        try:
            # Decrypt the event
            decrypted_event = await self._crypto.decrypt_megolm_event(event)

            # Convert to a regular MessageEvent and process
            if decrypted_event:
                # Create a mock MessageEvent with the decrypted content
                from mautrix.types import MessageEvent, RoomID, UserID

                # Create a new event with decrypted content
                decrypted_msg_event = MessageEvent(
                    content=decrypted_event,
                    type=EventType.ROOM_MESSAGE,
                    room_id=RoomID(event.room_id),
                    event_id=event.event_id,
                    sender=UserID(event.sender),
                    timestamp=event.timestamp,
                )

                # Process the decrypted message
                await self._on_message(decrypted_msg_event)
            else:
                logger.warning(f"Matrix [{self.instance_id}] Failed to decrypt event")
        except Exception as e:
            logger.opt(exception=True).error(
                f"Matrix [{self.instance_id}] Error decrypting message: {e}"
            )

    async def _on_message(self, event: MessageEvent) -> None:
        if self._client and event.sender == self._client.mxid:
            return

        content = event.content

        if isinstance(content, TextMessageEventContent):
            if content.msgtype not in (MessageType.TEXT, MessageType.EMOTE):
                return
            text = content.body or ""
            if not text.strip():
                return

            mentions = []
            # MSC3952: intentional mentions
            raw_mentions = content.get("m.mentions", {})
            if isinstance(raw_mentions, dict):
                user_ids = raw_mentions.get("user_ids", [])
                for uid in user_ids:
                    # Try to get display name
                    name, _ = await self._get_profile(uid)
                    mentions.append({"id": uid, "name": name})

            display_name, avatar = await self._get_profile(str(event.sender))
            await self.bridge.on_message(
                NormalizedMessage(
                    platform="matrix",
                    instance_id=self.instance_id,
                    channel={"room_id": str(event.room_id)},
                    nickname=display_name,
                    user_id=str(event.sender),
                    user_avatar=avatar,
                    text=text,
                    mentions=mentions,
                    source_proxy=self._proxy,
                )
            )

        elif isinstance(content, MediaMessageEventContent):
            match content.msgtype:
                case MessageType.IMAGE:
                    att_type = "image"
                case MessageType.VIDEO:
                    att_type = "video"
                case MessageType.AUDIO:
                    att_type = "voice"
                case _:
                    att_type = "file"

            # Honour declared size before downloading
            declared = getattr(content.info, "size", None) if content.info else None
            if declared and declared > self.config.max_file_size:
                logger.debug(
                    f"Matrix [{self.instance_id}] skipping {content.body!r}: {declared} > {self.config.max_file_size}"
                )
                return

            att_data: bytes | None = None
            att_url = ""
            mxc = content.url
            if mxc and self._client:
                try:
                    raw = await self._client.download_media(mxc)
                    if len(raw) <= self.config.max_file_size:
                        att_data = raw
                    else:
                        logger.debug(
                            f"Matrix [{self.instance_id}] {content.body!r} exceeds size limit"
                        )
                        return
                except Exception as e:
                    logger.warning(
                        f"Matrix [{self.instance_id}] media download failed: {e}"
                    )
                    att_url = self._mxc_to_http(str(mxc))

            display_name, avatar = await self._get_profile(str(event.sender))
            fname = getattr(content, "filename", None) or content.body or ""
            await self.bridge.on_message(
                NormalizedMessage(
                    platform="matrix",
                    instance_id=self.instance_id,
                    channel={"room_id": str(event.room_id)},
                    nickname=display_name,
                    user_id=str(event.sender),
                    user_avatar=avatar,
                    text="",
                    attachments=[
                        Attachment(
                            type=att_type, url=att_url, name=fname, data=att_data
                        )
                    ],
                    source_proxy=self._proxy,
                )
            )

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
        reply_to_event_id = None
        if reply_to_id:
            from mautrix.types import EventID

            reply_to_event_id = EventID(reply_to_id)

        if self._client is None:
            logger.warning(f"Matrix [{self.instance_id}] send: driver not started")
            return

        room_id = channel.get("room_id")
        if not room_id:
            logger.warning(
                f"Matrix [{self.instance_id}] send: no room_id in channel {channel}"
            )
            return

        rich_header = kwargs.get("rich_header")
        if rich_header:
            t = rich_header.get("title", "")
            c = rich_header.get("content", "")
            prefix = f"**{t}**" + (f" · *{c}*" if c else "")
            text = f"{prefix}\n{text}" if text else prefix

        mentions = kwargs.get("mentions", [])
        html_text = text
        is_html = False

        if mentions:
            import html

            # Escape the base text first so we don't double-escape the mention tags later
            # (Simplistic approach: if we switch to HTML, we should escape the original text)
            html_text = html.escape(text)
            for m in mentions:
                mention_link = f'<a href="https://matrix.to/#/{m["id"]}">{html.escape(m["name"])}</a>'
                # Replace @Name with link.
                # Note: text is already escaped, so we look for @Name
                # But wait, we need to be careful replacing in escaped text.
                # Let's assume @Name doesn't contain special chars for now or just replace carefully.
                html_text = html_text.replace(
                    f"@{html.escape(m['name'])}", mention_link
                )
            is_html = True

        relates_obj: RelatesTo | None = None
        if text.strip():
            relates_obj = (
                RelatesTo(in_reply_to=InReplyTo(event_id=reply_to_event_id))
                if reply_to_event_id
                else None
            )
            try:
                # If E2E is enabled, the client will automatically encrypt messages
                # to encrypted rooms. The crypto module handles this transparently.
                if is_html:
                    await self._client.send_text(
                        room_id, text, html=html_text, relates_to=relates_obj
                    )
                else:
                    await self._client.send_text(room_id, text, relates_to=relates_obj)
            except Exception as e:
                logger.error(f"Matrix [{self.instance_id}] send text failed: {e}")

        source_proxy = kwargs.get("source_proxy") or self._proxy
        for att in attachments or []:
            if not att.url and att.data is None:
                continue

            result = await media.fetch_attachment(
                att, self.config.max_file_size, source_proxy
            )
            if not result:
                label = att.name or att.url or ""
                await self._send_fallback(
                    room_id, f"[{att.type.capitalize()}: {label}]", relates_obj
                )
                continue

            data_bytes, mime = result
            fname = media.filename_for(att.name, mime)

            try:
                mxc_uri: ContentURI = await self._client.upload_media(
                    data=data_bytes,
                    mime_type=mime,
                    filename=fname,
                    size=len(data_bytes),
                )
            except Exception as e:
                logger.error(f"Matrix [{self.instance_id}] upload failed: {e}")
                label = att.name or att.url or fname
                await self._send_fallback(
                    room_id, f"[{att.type.capitalize()}: {label}]", relates_obj
                )
                continue

            try:
                await self._client.send_file(
                    room_id,
                    url=mxc_uri,
                    info=_make_info(att.type, mime, len(data_bytes)),
                    file_name=fname,
                    file_type=_FILE_TYPES.get(att.type, MessageType.FILE),
                    relates_to=relates_obj,
                )
            except Exception as e:
                logger.error(f"Matrix [{self.instance_id}] send media failed: {e}")

    async def _send_fallback(
        self, room_id: str, body: str, relates_obj: RelatesTo | None = None
    ) -> None:
        if self._client is None:
            return
        try:
            await self._client.send_text(RoomID(room_id), body, relates_to=relates_obj)
        except Exception as e:
            logger.error(f"Matrix [{self.instance_id}] fallback send failed: {e}")


register("matrix", MatrixConfig, MatrixDriver)
