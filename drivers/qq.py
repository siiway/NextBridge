# QQ driver for OneBot 11 WebSocket protocol.
# The QQ bot server acts as a WebSocket endpoint; this driver connects as a client,
# receives push events, and sends actions over the same connection.
#
# Config keys (under qq.<instance_id>):
#   ws_url        – WebSocket URL, e.g. "ws://127.0.0.1:3001"
#   ws_token      – Optional access token
#   max_file_size    – Max bytes to download when bridging media (default 10 MB)
#   file_send_mode   – How to upload files/videos to QQ: \"stream\" (default) or \"base64\"
#                      stream: chunked upload_file_stream → upload_group_file with path
#                      base64: upload_group_file with base64:// payload directly
#   stream_threshold – If > 0, force stream mode when file exceeds this many bytes,
#                      regardless of file_send_mode (default 0 = disabled)

import asyncio
import base64
import datetime
import html
import json
import math
import ssl
import tempfile
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Any, Literal

import websockets
import websockets.exceptions
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response

import services.logger as log
from drivers import BaseDriver
from drivers.registry import register
from services import cqface, media
from services.config import UNSET, get_proxy
from services.config import get as get_config
from services.config_schema import _DriverConfig
from services.db import msg_db
from services.message import Attachment, NormalizedMessage
from services.message_format import parse_richheader_tag
from services.util import mask_url_credentials


class QqConfig(_DriverConfig):
    protocol: Literal["napcat", "lagrange", "onebot_v11"] = "napcat"
    ws_url: str = "ws://127.0.0.1:3001"
    ws_token: str = ""
    ws_ssl_verify: bool = True
    max_file_size: int = 10 * 1024 * 1024
    file_send_mode: Literal["stream", "base64"] = "stream"
    cqface_mode: Literal["gif", "emoji"] = "gif"
    stream_threshold: int = 0
    forward_render_enabled: bool = False
    forward_render_ttl_seconds: int = 180 * 24 * 60 * 60
    forward_render_mount_path: str = "/qq-forward"
    forward_render_persist_enabled: bool = False
    # Merged-forward image rendering method:
    # - "url": store bytes in DB and serve via bridge URL (default)
    # - "base64": embed data URI directly in HTML
    forward_render_image_method: Literal["url", "base64"] = "url"
    forward_render_asset_ttl_seconds: int = 14 * 24 * 60 * 60
    # Preferred public URL prefix for forward links. When set, forward links are
    # generated as: {forward_render_base_url}/{page_id}
    # (mount path is NOT appended automatically).
    forward_render_base_url: str = ""
    # Merged-forward face rendering strategy:
    # - false: render by cqface mapping (unicode)
    # - true/unset: render by default gif host
    # - string: use custom gif host base URL
    forward_render_cqface_gif: bool | str = True
    # QQ has no native "edit message" API. When an edit is bridged from another
    # platform (e.g. Discord/Telegram), simulate it by sending a NEW message that
    # quotes (replies to) the original bridged message and prepends `edit_prefix`.
    edit_via_reply: bool = True
    edit_prefix: str = "[编辑]"
    # Message recall/delete bridging. When enabled, a recall on QQ is fanned out
    # to other platforms, and a recall bridged from another platform deletes the
    # corresponding QQ message via the native `delete_msg` API.
    enable_recall: bool = True
    proxy: str | None = UNSET


_DEFAULT_FORWARD_CQFACE_GIF_HOST: str = "https://nextbridge.siiway.org/db/cqface-gif/"
_FORWARD_TEMPLATE_PATH: Path = (
    Path(__file__).resolve().parent.parent / "templates" / "qq_forward_template.html"
)

_FORWARD_PAGE_TEMPLATE = Template(
    """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /><title>$title</title></head>
<body><main><h1>$title</h1><div class="meta">$meta_primary</div><div class="meta sub">$meta_secondary</div>$body</main></body>
</html>"""
)


_logger = log.get_logger("qq")


@lru_cache(maxsize=1)
def _get_forward_page_template() -> Template:
    try:
        text = _FORWARD_TEMPLATE_PATH.read_text(encoding="utf-8")
        return Template(text)
    except OSError as exc:
        _logger.warning(
            f"Failed to load forward template {_FORWARD_TEMPLATE_PATH}: {exc}"
        )
        return _FORWARD_PAGE_TEMPLATE


@dataclass(slots=True)
class _ForwardPage:
    html_content: str
    created_at: datetime.datetime
    expires_at: datetime.datetime
    destroyed_at: datetime.datetime | None = None


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


# ---------------------------------------------------------------------------
# CQ face GIF database
# ---------------------------------------------------------------------------

# Resolved once at import time so path traversal checks are always anchored to
# the same absolute directory, even if the working directory changes.
_FACE_DB: Path = (Path(__file__).parent.parent / "db" / "cqface-gif").resolve()


def _load_face_gif(face_id_raw) -> bytes | None:
    """
    Safely load a QQ face GIF from the local database.

    Security:
    - Layer 1: The face ID is parsed as a non-negative integer.  Integers
      cannot contain path separators or ``..``, so no traversal is possible
      by construction.
    - Layer 2: The resolved candidate path is checked with
      ``Path.is_relative_to(_FACE_DB)`` as a hard guarantee — this catches
      any edge cases such as OS-level symlinks that point outside the db dir.

    Returns ``None`` if the ID is invalid, escapes the database directory,
    or the file simply does not exist.
    """
    try:
        face_id = int(face_id_raw)
        if face_id < 0:
            raise ValueError("negative id")
    except (TypeError, ValueError):
        _logger.warning(f"Invalid face ID {face_id_raw!r} — ignored")
        return None

    candidate = (_FACE_DB / f"{face_id}.gif").resolve()

    # Layer 2 path-traversal guard.
    if not candidate.is_relative_to(_FACE_DB):
        _logger.warning(f"Face path {candidate} escapes database dir — blocked")
        return None

    if not candidate.is_file():
        return None

    try:
        return candidate.read_bytes()
    except OSError as e:
        _logger.error(f"Failed to read face GIF {candidate}: {e}")
        return None


class QqDriver(BaseDriver[QqConfig]):
    platform_name = "qq"

    def __init__(self, instance_id: str, config: QqConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._ws: Any = None  # websockets connection (type varies by version)
        # echo_id → Future; used to await responses for specific actions
        self._pending: dict[str, asyncio.Future] = {}
        # Serialize WebSocket sends: concurrent _call() invocations must not
        # interleave frames on the same connection (large payloads split into
        # multiple frames would corrupt the outgoing JSON action).
        self._send_lock = asyncio.Lock()
        self._proxy = get_proxy(config.proxy)
        # Cache for user qid to avoid repeated API calls
        self._qid_cache: dict[str, str] = {}
        # user_id → monotonic timestamp of last failed qid lookup (negative cache)
        self._qid_miss_cache: dict[str, float] = {}
        self._forward_pages: dict[str, _ForwardPage] = {}
        self._forward_file_url_cache: dict[str, str | None] = {}
        self._forward_gc_task: asyncio.Task | None = None
        self._forward_mount_registered = False
        # Ordered FIFO queue + single worker: events must be processed in the
        # order they arrive on the WebSocket, otherwise bridged messages can be
        # reordered (fire-and-forget create_task interleaves concurrent handlers).
        self._event_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._event_worker_task: asyncio.Task | None = None
        # Message IDs we deleted ourselves (bridged recalls). Used to ignore the
        # recall notice NapCat echoes back so we don't loop.
        self._recall_suppress: set[str] = set()
        self._essence_msg_ids: dict[str, set[str]] = {}
        self._essence_poll_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self.bridge.register_sender(self.instance_id, self.send)
        if self.config.edit_via_reply:
            self.bridge.register_editor(self.instance_id, self.edit)
        if self.config.enable_recall:
            self.bridge.register_deleter(self.instance_id, self.delete)
        self.bridge.register_pinner(self.instance_id, self.pin)
        self.bridge.register_unpinner(self.instance_id, self.unpin)
        self._ensure_forward_http_mount()
        self._ensure_forward_gc_task()
        if self._event_worker_task is None or self._event_worker_task.done():
            self._event_worker_task = asyncio.create_task(self._event_worker())

        ws_url = self.config.ws_url
        if self.config.ws_token:
            sep = "&" if "?" in ws_url else "?"
            ws_url = f"{ws_url}{sep}access_token={self.config.ws_token}"

        self.logger.info(f"connecting to {mask_url_credentials(ws_url)}")

        connect_kwargs: dict
        if self._proxy:
            self.logger.debug(f"using proxy {mask_url_credentials(self._proxy)}")
            connect_kwargs = {"proxy": self._proxy}
        else:
            connect_kwargs = {}

        if ws_url.lower().startswith("wss://") and not self.config.ws_ssl_verify:
            # Allow self-signed/private CA certificates when explicitly requested.
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            connect_kwargs["ssl"] = ssl_context
            self.logger.warning(
                f"NapCat [{self.instance_id}] TLS certificate verification is disabled for WebSocket"
            )

        while True:
            try:
                async with websockets.connect(ws_url, **connect_kwargs) as ws:
                    self._ws = ws
                    self.logger.info("connected")
                    await self._listen(ws)
            except websockets.exceptions.ConnectionClosedOK:
                self.logger.info("connection closed normally")
            except ssl.SSLCertVerificationError as e:
                self.logger.error(
                    f"NapCat [{self.instance_id}] TLS certificate verification failed: {e}. "
                    "If your server uses a self-signed cert, set qq.<instance_id>.ws_ssl_verify=false"
                )
            except Exception as e:
                self.logger.error(f"connection error: {e}")
            finally:
                self._ws = None

            self.logger.info("reconnecting in 5s...")
            await asyncio.sleep(5)

    def _normalize_mount_path(self, path: str) -> str:
        normalized = (path or "/qq-forward").strip()
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        if len(normalized) > 1 and normalized.endswith("/"):
            normalized = normalized[:-1]
        return normalized

    def _forward_mount_path(self) -> str:
        configured = self._normalize_mount_path(self.config.forward_render_mount_path)
        if configured == "/qq-forward":
            return f"/qq-forward/{self.instance_id}"
        return configured

    def _supports_forward_api(self) -> bool:
        return self.config.protocol in {"napcat", "lagrange"}

    def _supports_stream_file_upload(self) -> bool:
        return self.config.protocol == "napcat"

    def _coerce_forward_ttl_seconds(self, raw: Any) -> int | None:
        try:
            ttl = int(raw)
        except (TypeError, ValueError):
            return None
        return max(60, ttl)

    def _resolve_rule_forward_ttl(self, source_group_id: str) -> int | None:
        if not source_group_id:
            return None

        rules = getattr(self.bridge, "_rules", [])
        for rule in rules:
            if not isinstance(rule, dict):
                continue

            if rule.get("type") == "connect":
                channels = rule.get("channels") or {}
                src = channels.get(self.instance_id)
                if not isinstance(src, dict):
                    continue
                if str(src.get("group_id", "")) != str(source_group_id):
                    continue

                src_msg = src.get("msg")
                if isinstance(src_msg, dict):
                    ttl = self._coerce_forward_ttl_seconds(
                        src_msg.get("forward_render_ttl_seconds")
                    )
                    if ttl is not None:
                        return ttl

                rule_msg = rule.get("msg")
                if isinstance(rule_msg, dict):
                    ttl = self._coerce_forward_ttl_seconds(
                        rule_msg.get("forward_render_ttl_seconds")
                    )
                    if ttl is not None:
                        return ttl
                continue

            from_cfg = rule.get("from") or {}
            src = from_cfg.get(self.instance_id)
            if not isinstance(src, dict):
                continue
            if str(src.get("group_id", "")) != str(source_group_id):
                continue

            src_msg = src.get("msg")
            if isinstance(src_msg, dict):
                ttl = self._coerce_forward_ttl_seconds(
                    src_msg.get("forward_render_ttl_seconds")
                )
                if ttl is not None:
                    return ttl

            rule_msg = rule.get("msg")
            if isinstance(rule_msg, dict):
                ttl = self._coerce_forward_ttl_seconds(
                    rule_msg.get("forward_render_ttl_seconds")
                )
                if ttl is not None:
                    return ttl

        return None

    def _effective_forward_ttl(self, source_group_id: str = "") -> int:
        base_ttl = max(60, int(self.config.forward_render_ttl_seconds or 0))
        override_ttl = self._resolve_rule_forward_ttl(source_group_id)
        return override_ttl if override_ttl is not None else base_ttl

    def _effective_forward_asset_ttl(self) -> int:
        return max(0, int(self.config.forward_render_asset_ttl_seconds or 0))

    def _forward_public_prefix(self) -> str:
        direct_base = (self.config.forward_render_base_url or "").strip().rstrip("/")
        if direct_base:
            return direct_base

        mount_path = self._forward_mount_path()
        base = str(get_config("global.base_url", "") or "").rstrip("/")

        if not base and self.http_server is not None:
            host = self.http_server.host or "127.0.0.1"
            if host == "0.0.0.0":
                host = "127.0.0.1"
            root_path = (self.http_server.root_path or "").rstrip("/")
            base = f"http://{host}:{self.http_server.port}{root_path}"

        if not base:
            base = "http://127.0.0.1:9080"

        return f"{base}{mount_path}"

    def _build_forward_page_url(self, page_id: str) -> str:
        return f"{self._forward_public_prefix()}/{page_id}"

    def _build_forward_asset_url(self, asset_id: str) -> str:
        return f"./asset/{asset_id}"

    def _ensure_forward_http_mount(self) -> None:
        if not self.config.forward_render_enabled:
            return
        if self.http_server is None:
            self.logger.warning(
                f"NapCat [{self.instance_id}] forward renderer not mounted: shared HTTP server unavailable"
            )
            return
        if self._forward_mount_registered:
            return

        app = FastAPI()

        @app.get("/{page_id}", response_class=HTMLResponse)
        async def _get_forward_page(page_id: str) -> HTMLResponse:
            page = self._forward_pages.get(page_id)
            if page is None and self.config.forward_render_persist_enabled:
                stored = msg_db().get_forward_page(page_id)
                if stored is not None:
                    page = _ForwardPage(
                        html_content=str(stored.get("html_content", "")),
                        created_at=datetime.datetime.fromtimestamp(
                            int(stored.get("created_at", 0)), datetime.UTC
                        ),
                        expires_at=datetime.datetime.fromtimestamp(
                            int(stored.get("expires_at", 0)), datetime.UTC
                        ),
                        destroyed_at=(
                            datetime.datetime.fromtimestamp(
                                int(stored.get("destroyed_at", 0)), datetime.UTC
                            )
                            if stored.get("destroyed_at")
                            else None
                        ),
                    )
                    self._forward_pages[page_id] = page

            if page is None:
                raise HTTPException(status_code=404, detail="Forward page not found")

            if page.destroyed_at is not None:
                self._forward_pages.pop(page_id, None)
                raise HTTPException(status_code=404, detail="Forward page destroyed")

            if page.expires_at <= _utc_now() and page.destroyed_at is None:
                page.destroyed_at = _utc_now()
                if self.config.forward_render_persist_enabled:
                    msg_db().mark_forward_page_destroyed(
                        page_id, int(page.destroyed_at.timestamp())
                    )

            return HTMLResponse(content=page.html_content, status_code=200)

        @app.get("/asset/{asset_id}")
        async def _get_forward_asset(asset_id: str) -> Response:
            asset = msg_db().get_forward_asset(asset_id)
            if asset is None:
                raise HTTPException(status_code=404, detail="Forward asset not found")

            expires_at = asset.get("expires_at")
            now = int(_utc_now().timestamp())
            if expires_at is not None and int(expires_at) <= now:
                raise HTTPException(status_code=404, detail="Forward asset expired")

            data = asset.get("data") or b""
            mime = str(asset.get("mime") or "application/octet-stream")
            headers = {
                "Cache-Control": (
                    "public, max-age=31536000, immutable"
                    if expires_at is None
                    else f"public, max-age={max(0, int(expires_at) - now)}"
                )
            }
            return Response(content=data, media_type=mime, headers=headers)

        mount_path = self._forward_mount_path()
        self.http_server.mount(
            instance_id=f"{self.instance_id}/forward",
            path=mount_path,
            app=app,
        )
        self._forward_mount_registered = True
        self.logger.info(
            f"NapCat [{self.instance_id}] forward renderer mounted at {mount_path}"
        )

    def _ensure_forward_gc_task(self) -> None:
        if not self.config.forward_render_enabled:
            return
        if self._forward_gc_task and not self._forward_gc_task.done():
            return
        self._forward_gc_task = asyncio.create_task(self._forward_gc_loop())

    async def _forward_gc_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            now = _utc_now()
            expired = [
                page_id
                for page_id, page in self._forward_pages.items()
                if page.expires_at <= now
            ]
            for page_id in expired:
                if self.config.forward_render_persist_enabled:
                    msg_db().mark_forward_page_destroyed(page_id, int(now.timestamp()))
                self._forward_pages.pop(page_id, None)
            deleted_assets = msg_db().purge_expired_forward_assets(int(now.timestamp()))
            if deleted_assets:
                self.logger.debug(
                    f"NapCat [{self.instance_id}] purged {deleted_assets} expired forward asset(s)"
                )

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def _listen(self, ws):
        async for raw in ws:
            try:
                data = json.loads(raw)
                # Action responses carry an "echo" field and "status" — route
                # them to any waiting _call() coroutine, then skip normal handling.
                echo = data.get("echo")
                if echo and echo in self._pending:
                    fut = self._pending.pop(echo)
                    if not fut.done():
                        fut.set_result(data)
                    continue
                self._spawn_event_task(data)
            except json.JSONDecodeError:
                self.logger.warning("invalid JSON received")
            except Exception as e:
                self.logger.error(f"handler error: {e}")

    def _spawn_event_task(self, data: dict) -> None:
        # Enqueue for the single ordered worker instead of firing a detached
        # task. This preserves WebSocket arrival order through to the bridge.
        self._event_queue.put_nowait(data)

    async def _event_worker(self) -> None:
        while True:
            data = await self._event_queue.get()
            try:
                await self._handle(data)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger.error(f"async handler error: {e}")
            finally:
                self._event_queue.task_done()

    async def _handle(self, data: dict):
        # Action responses carry an "echo" field — ignore them
        if data.get("post_type") is None:
            return

        post_type = data.get("post_type")

        if post_type == "notice":
            await self._on_notice(data)
            return

        if post_type != "message":
            return

        if data.get("message_type") == "group":
            await self._on_group_message(data)
        elif data.get("message_type") == "private":
            await self._on_private_message(data)

    async def _on_notice(self, event: dict):
        """Handle OneBot notice events (recall, essence/pin)."""
        notice_type = event.get("notice_type")

        if notice_type == "essence":
            await self._on_essence_notice(event)
            return

        if not self.config.enable_recall:
            return

        if notice_type not in ("group_recall", "friend_recall"):
            return

        message_id = str(event.get("message_id", ""))
        if not message_id:
            return

        # Ignore recalls we initiated ourselves (the notice NapCat echoes back
        # for our own delete_msg call) to avoid an infinite recall loop.
        if message_id in self._recall_suppress:
            self._recall_suppress.discard(message_id)
            return

        self_id = str(event.get("self_id", ""))
        # The author of the recalled message. When it is the bot itself the
        # recalled message is a bridged copy, so skip to avoid loops.
        author_id = str(event.get("user_id", ""))
        if author_id and author_id == self_id:
            return

        if notice_type == "group_recall":
            channel = {"group_id": str(event.get("group_id", ""))}
        else:
            channel = {"user_id": author_id}

        self.logger.debug(
            f"NapCat [{self.instance_id}] recall notice ({notice_type}) "
            f"for message {message_id}"
        )

        msg = NormalizedMessage(
            platform=self.platform_name,
            instance_id=self.instance_id,
            channel=channel,
            message_id=message_id,
            recall_target_id=message_id,
            is_recall=True,
            source_self_id=self_id,
        )
        await self.bridge.on_recall_message(msg)

    async def _on_essence_notice(self, event: dict):
        sub_type = event.get("sub_type")
        message_id = str(event.get("message_id", ""))
        group_id = str(event.get("group_id", ""))
        if not message_id or not group_id:
            self.logger.info(
                f"NapCat [{self.instance_id}] essence notice missing fields: "
                f"sub_type={sub_type} event={event}"
            )
            return

        channel = {"group_id": group_id}
        self_id = str(event.get("self_id", ""))

        self.logger.info(
            f"NapCat [{self.instance_id}] essence notice ({sub_type}) "
            f"for message {message_id} in group {group_id}"
        )

        if sub_type == "delete":
            msg = NormalizedMessage(
                platform=self.platform_name,
                instance_id=self.instance_id,
                channel=channel,
                message_id=message_id,
                unpin_target_id=message_id,
                is_unpin=True,
                source_self_id=self_id,
            )
            await self.bridge.on_unpin_message(msg)
        elif sub_type == "add":
            self._essence_msg_ids.setdefault(group_id, set()).add(message_id)
            self._ensure_essence_polling_task()

            msg = NormalizedMessage(
                platform=self.platform_name,
                instance_id=self.instance_id,
                channel=channel,
                message_id=message_id,
                pin_target_id=message_id,
                is_pin=True,
                source_self_id=self_id,
            )
            await self.bridge.on_pin_message(msg)

    def _ensure_essence_polling_task(self) -> None:
        if self._essence_poll_task and not self._essence_poll_task.done():
            return
        self._essence_poll_task = asyncio.create_task(self._essence_poll_loop())

    async def _essence_poll_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            for group_id in list(self._essence_msg_ids.keys()):
                try:
                    items = await self._api_get_essence_msg_list(group_id)
                except Exception as e:
                    self.logger.debug(f"essence poll failed for group {group_id}: {e}")
                    continue

                current_ids = {str(item.get("message_id", "")) for item in items}
                prev_ids = self._essence_msg_ids.get(group_id, set())

                removed = prev_ids - current_ids
                if not removed:
                    continue

                self._essence_msg_ids[group_id] = current_ids
                for mid in removed:
                    self.logger.info(
                        f"NapCat [{self.instance_id}] essence removed (poll) "
                        f"for message {mid} in group {group_id}"
                    )
                    msg = NormalizedMessage(
                        platform=self.platform_name,
                        instance_id=self.instance_id,
                        channel={"group_id": group_id},
                        message_id=mid,
                        unpin_target_id=mid,
                        is_unpin=True,
                    )
                    await self.bridge.on_unpin_message(msg)

    async def _on_private_message(self, event: dict):
        if event.get("user_id") == event.get("self_id"):
            return

        user_id = str(event.get("user_id", ""))
        sender = event.get("sender", {})
        nickname = sender.get("nickname") or user_id
        self.logger.debug(
            f"NapCat [{self.instance_id}] private message from {nickname}({user_id})"
        )

        time = event.get("time")

        face_as_emoji: bool = self.config.cqface_mode == "emoji"
        text, attachments, reply_id, mentions = await self._parse_message(
            event, face_as_emoji=face_as_emoji
        )

        if not text.strip() and not attachments:
            self.logger.debug(
                f"NapCat [{self.instance_id}] ignoring empty private message from {nickname}({user_id})"
            )
            return

        avatar_url = f"https://q.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640"
        self_id = str(event.get("self_id", ""))
        source_mentioned_self = any(str(m.get("id", "")) == self_id for m in mentions)

        msg = NormalizedMessage(
            platform=self.platform_name,
            instance_id=self.instance_id,
            channel={"user_id": user_id},
            nickname=nickname,
            user_id=user_id,
            user_avatar=avatar_url,
            text=text,
            attachments=attachments,
            message_id=str(event.get("message_id", "")),
            reply_parent=reply_id,
            mentions=mentions,
            source_self_id=self_id,
            source_mentioned_self=source_mentioned_self,
            time=datetime.datetime.fromtimestamp(time).isoformat() if time else None,
            source_proxy=self._media_proxy,
            username="",
            is_dm=True,
        )
        await self.bridge.on_message(msg)

    async def _on_group_message(self, event: dict):
        # NapCat echoes the bot's own sent messages back as real events;
        # self_id is the bot's QQ number, present on every OneBot 11 event.
        if event.get("user_id") == event.get("self_id"):
            return

        group_id = str(event.get("group_id", ""))
        user_id = str(event.get("user_id", ""))
        message_id = str(event.get("message_id", ""))
        message_seq = str(
            event.get("message_seq", event.get("seq", event.get("real_id", "")))
        )
        sender = event.get("sender", {})
        # Prefer group card (nickname-in-group) over global nickname
        nickname = sender.get("card") or sender.get("nickname") or user_id
        self.logger.debug(
            f"NapCat [{self.instance_id}] message from {nickname}({user_id}) "
            f"group={group_id} message_id={message_id} seq={message_seq}"
        )
        time = event.get("time")
        face_as_emoji: bool = self.config.cqface_mode == "emoji"
        text, attachments, reply_id, mentions = await self._parse_message(
            event,
            face_as_emoji=face_as_emoji,
            source_group_id=group_id,
        )
        self_id = str(event.get("self_id", ""))
        source_mentioned_self = any(str(m.get("id", "")) == self_id for m in mentions)
        if not text.strip() and not attachments:
            self.logger.debug(
                f"NapCat [{self.instance_id}] ignoring empty message from {nickname}({user_id})"
            )
            return

        # Use qid for username when available (only after the empty check, so
        # ignored messages don't trigger a blocking get_stranger_info call).
        qid = (await self._get_qid(user_id, group_id)).strip()

        # QQ avatar endpoint (public, no auth)
        avatar_url = f"https://q.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640"

        msg = NormalizedMessage(
            platform=self.platform_name,
            instance_id=self.instance_id,
            channel={"group_id": group_id},
            nickname=nickname,
            user_id=user_id,
            user_avatar=avatar_url,
            text=text,
            attachments=attachments,
            message_id=str(event.get("message_id", "")),
            reply_parent=reply_id,
            mentions=mentions,
            source_self_id=self_id,
            source_mentioned_self=source_mentioned_self,
            time=datetime.datetime.fromtimestamp(time).isoformat() if time else None,
            source_proxy=self._media_proxy,
            username=qid,
        )
        await self.bridge.on_message(msg)

    async def _parse_message(
        self,
        event: dict,
        *,
        face_as_emoji: bool = False,
        source_group_id: str = "",
    ) -> tuple[str, list[Attachment], str | None, list[dict]]:
        """
        Parse an OneBot 11 message event into plain text + attachments + reply_id + mentions.
        Always uses the structured ``message`` segment array; CQ-code strings
        in ``raw_message`` are only used as a last-resort text fallback.
        """
        segments = event.get("message", [])

        # If NapCat sent a plain string instead of an array, treat as text only
        if isinstance(segments, str):
            return segments, [], None, []

        text_parts: list[str] = []
        attachments: list[Attachment] = []
        reply_id: str | None = next(
            (
                str(seg.get("data", {}).get("id", ""))
                for seg in segments
                if seg.get("type") == "reply"
            ),
            None,
        )
        mentions: list[dict] = []

        self_id = str(event.get("self_id", ""))
        strip_next_space = False
        is_first_text = True

        for seg in segments:
            t = seg.get("type", "")
            d = seg.get("data", {})

            match t:
                case "text":
                    t_str = d.get("text", "")
                    if strip_next_space and t_str.startswith(" "):
                        t_str = t_str[1:]
                    strip_next_space = False
                    if t_str:
                        is_first_text = False
                        text_parts.append(t_str)

                case "at":
                    qq = str(d.get("qq", ""))
                    name = d.get("name")
                    if not name and qq != "all":
                        # Try to look up name in our DB
                        name = msg_db().get_user_name(self.instance_id, qq)

                    if not name and qq != "all" and source_group_id:
                        # Try to fetch from API
                        try:
                            data = await self._api_get_group_member_info(
                                source_group_id, qq
                            )
                            if data:
                                name = data.get("card") or data.get("nickname")
                                if name:
                                    msg_db().save_user(self.instance_id, qq, name)
                        except Exception as e:
                            self.logger.debug(
                                f"NapCat [{self.instance_id}] failed to fetch member info for {qq}: {e}"
                            )

                    if not name:
                        name = qq

                    # Strip auto-mention of self when replying
                    if qq == self_id and reply_id and is_first_text:
                        strip_next_space = True
                        if qq and qq != "all":
                            mentions.append({"id": qq, "name": name})
                        continue

                    is_first_text = False
                    text_parts.append(f"@{name}")
                    if qq and qq != "all":
                        mentions.append({"id": qq, "name": name})

                case "image":
                    url = d.get("url") or d.get("file", "")
                    name = d.get("file", "image.jpg")
                    attachments.append(Attachment(type="image", url=url, name=name))

                case "record":  # voice message
                    url = self._segment_url(d)
                    name = self._segment_name(d, "voice.amr")
                    if url:
                        attachments.append(Attachment(type="voice", url=url, name=name))
                    else:
                        attachments.append(await self._resolve_record_attachment(d))

                case "video":
                    url = d.get("url") or d.get("file", "")
                    name = d.get("file", "video.mp4")
                    attachments.append(Attachment(type="video", url=url, name=name))

                case "file":
                    url = d.get("url") or d.get("path", "")
                    # NapCat puts the actual filename in "file"; "name" is not used
                    name = d.get("file") or d.get("name", "file")
                    try:
                        size = int(d.get("file_size", d.get("size", -1)))
                    except (TypeError, ValueError):
                        size = -1
                    attachments.append(
                        Attachment(type="file", url=url, name=name, size=size)
                    )

                case "face":
                    face_id_raw = d.get("id", "")
                    if face_as_emoji:
                        try:
                            text_parts.append(f":cqface{int(face_id_raw)}:")
                        except (TypeError, ValueError):
                            pass
                    else:
                        gif_data = _load_face_gif(face_id_raw)
                        if gif_data is not None:
                            # face_id is validated integer at this point
                            name = f"face_{int(face_id_raw)}.gif"
                            attachments.append(
                                Attachment(
                                    type="image", url="", name=name, data=gif_data
                                )
                            )

                case "json":
                    # Rich JSON message (contact card, news, mini-app, etc.)
                    # The `data` field is a JSON string; `prompt` is always a
                    # human-readable summary provided by the QQ client.
                    raw_json = d.get("data", "")
                    try:
                        obj = (
                            json.loads(raw_json)
                            if isinstance(raw_json, str)
                            else raw_json
                        )
                        prompt = obj.get("prompt", "").strip()
                        if prompt:
                            text_parts.append(f"[{prompt}]")
                        else:
                            # Try to build a summary from common fields
                            meta = obj.get("meta", {})
                            for key in ("news", "music", "contact", "detail_1"):
                                sub = meta.get(key)
                                if isinstance(sub, dict):
                                    title = (
                                        sub.get("title") or sub.get("nickname") or ""
                                    )
                                    desc = sub.get("desc") or sub.get("tag") or ""
                                    parts = [p for p in (title, desc) if p]
                                    if parts:
                                        text_parts.append(f"[{': '.join(parts)}]")
                                        break
                            else:
                                text_parts.append("[App message]")
                    except (json.JSONDecodeError, AttributeError):
                        text_parts.append("[App message]")

                case "reply":
                    # Quote/reply handled in pre-pass
                    pass

                case "forward":
                    # Merged forwarded message chain
                    forward_text = await self._render_forward_segment(
                        d,
                        source_group_id=source_group_id,
                    )
                    text_parts.append(forward_text)

                case "mface":
                    # Market/sticker face — use summary text if present
                    summary = d.get("summary", "").strip()
                    if summary:
                        text_parts.append(summary)

                case "share":
                    # URL share card
                    title = d.get("title", "").strip()
                    url = d.get("url", "").strip()
                    if title and url:
                        text_parts.append(f"[Share: {title}] {url}")
                    elif url:
                        text_parts.append(f"[Share] {url}")

                case "location":
                    name = d.get("name", "").strip()
                    address = d.get("address", "").strip()
                    parts = [p for p in (name, address) if p]
                    text_parts.append(
                        f"[Location: {', '.join(parts)}]" if parts else "[Location]"
                    )

                case "music":
                    title = d.get("title", "").strip()
                    singer = d.get("singer", d.get("author", "")).strip()
                    if title:
                        text_parts.append(
                            f"[Music: {title}"
                            + (f" — {singer}" if singer else "")
                            + "]"
                        )
                    else:
                        text_parts.append("[Music]")

                # poke, basketball, dice, rps, etc. — silently skip

        text = "".join(text_parts)
        # If segments gave us nothing useful, fall back to raw_message string
        if not text and not attachments:
            text = event.get("raw_message", "")

        return text, attachments, reply_id, mentions

    def _normalize_cqface_gif_host(self, host: str) -> str:
        normalized = (host or "").strip()
        if not normalized:
            return ""
        if not normalized.startswith(("http://", "https://")):
            normalized = f"https://{normalized.lstrip('/')}"
        if not normalized.endswith("/"):
            normalized = f"{normalized}/"
        return normalized

    def _forward_cqface_gif_host(self) -> str:
        cfg = self.config.forward_render_cqface_gif

        if cfg is False:
            return ""
        if cfg is True:
            return _DEFAULT_FORWARD_CQFACE_GIF_HOST
        if isinstance(cfg, str):
            custom = self._normalize_cqface_gif_host(cfg)
            if custom:
                return custom
            return _DEFAULT_FORWARD_CQFACE_GIF_HOST

        return _DEFAULT_FORWARD_CQFACE_GIF_HOST

    async def _upload_file_from_bytes(
        self,
        data_bytes: bytes,
        filename: str,
        target_id: str,
        *,
        upload_api: str = "upload_group_file",
        id_key: str = "group_id",
    ) -> bool:
        with tempfile.NamedTemporaryFile(
            prefix="nextbridge-qq-",
            suffix=f"-{Path(filename).name}",
            delete=False,
        ) as tmp:
            tmp.write(data_bytes)
            tmp_path = tmp.name

        try:
            resp = await self._call(
                upload_api,
                {
                    id_key: int(target_id),
                    "file": tmp_path,
                    "name": filename,
                },
            )
            if resp and resp.get("status") == "ok":
                return True
            self.logger.warning(
                f"QQ [{self.instance_id}] {upload_api} failed for '{filename}': {resp}"
            )
            return False
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass

    def _render_forward_face_segment_html(self, seg_data: dict) -> str:
        face_id = str(seg_data.get("id", "")).strip()
        if not face_id:
            return self._bilingual("\u8868\u60c5", "Sticker")

        gif_host = self._forward_cqface_gif_host()
        if not gif_host:
            return html.escape(cqface.resolve_cqface(face_id))

        main_url = f"{gif_host}{face_id}.gif"
        alt_text = cqface.resolve_cqface(face_id)

        return (
            f"<img class='cqface' src='{html.escape(main_url)}' "
            f"alt='{html.escape(alt_text)}' title='cqface:{html.escape(face_id)}'/>"
        )

    @staticmethod
    def _is_safe_forward_image_mime(mime: str) -> bool:
        normalized = (mime or "").split(";", 1)[0].strip().lower()
        # Block script-capable or non-image payloads from being embedded/served.
        return normalized in {
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/webp",
            "image/bmp",
            "image/avif",
        }

    @staticmethod
    def _segment_url(seg_data: dict) -> str:
        url = (
            seg_data.get("url")
            or seg_data.get("src")
            or seg_data.get("path")
            or seg_data.get("file")
            or ""
        )
        url = str(url).strip()
        if url.startswith(("http://", "https://")):
            return url
        return ""

    @staticmethod
    def _segment_name(seg_data: dict, fallback: str) -> str:
        return str(seg_data.get("name") or seg_data.get("file") or fallback)

    def _render_forward_asset_html(
        self,
        seg_data: dict,
        *,
        kind_label: str,
        kind_class: str,
        fallback_name: str,
    ) -> str:
        name = html.escape(self._segment_name(seg_data, fallback_name))
        url = self._segment_url(seg_data)
        if not url:
            return f"[{kind_label}: {name}]"

        safe_url = html.escape(url)
        if kind_class == "voice":
            return (
                f"<div class='media-block media-voice'>"
                f"<span class='chip'>{kind_label}</span>"
                f"<audio class='media-player' controls preload='none' src='{safe_url}'></audio>"
                f"<a class='asset {html.escape(kind_class)}' href='{safe_url}' target='_blank' rel='noopener noreferrer'>"
                f"{name}</a>"
                f"</div>"
            )
        if kind_class == "video":
            return (
                f"<div class='media-block media-video'>"
                f"<span class='chip'>{kind_label}</span>"
                f"<video class='media-player' controls preload='metadata' src='{safe_url}'></video>"
                f"<a class='asset {html.escape(kind_class)}' href='{safe_url}' target='_blank' rel='noopener noreferrer'>"
                f"{name}</a>"
                f"</div>"
            )
        return (
            f"<span class='chip'>{kind_label}</span>"
            f"<a class='asset {html.escape(kind_class)}' href='{safe_url}' "
            "target='_blank' rel='noopener noreferrer'>"
            f"{name}</a>"
        )

    async def _render_forward_voice_asset_html(self, seg_data: dict) -> str:
        name = html.escape(self._segment_name(seg_data, "voice.amr"))
        url = self._segment_url(seg_data)
        if not url:
            return self._bilingual(f"语音: {name}", f"Voice: {name}")

        attachment = Attachment(
            type="voice", url=url, name=self._segment_name(seg_data, "voice.amr")
        )
        result = await media.fetch_attachment(
            attachment,
            max_bytes=max(1, int(self.config.max_file_size or 10 * 1024 * 1024)),
            proxy=self._media_proxy,
        )
        if not result:
            safe_url = html.escape(url)
            return (
                "<div class='media-block media-voice'>"
                "<span class='chip'>" + self._bilingual("语音", "Voice") + "</span>"
                f"<a class='asset voice' href='{safe_url}' target='_blank' rel='noopener noreferrer'>"
                f"{name}</a>"
                "</div>"
            )

        data, mime = result
        data_url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        safe_data_url = html.escape(data_url)
        safe_url = html.escape(url)
        return (
            "<div class='media-block media-voice'>"
            "<span class='chip'>" + self._bilingual("语音", "Voice") + "</span>"
            f"<audio class='media-player' controls preload='none' src='{safe_data_url}'></audio>"
            f"<a class='asset voice' href='{safe_url}' target='_blank' rel='noopener noreferrer'>"
            f"{name}</a>"
            "</div>"
        )

    async def _render_forward_image_asset_html(
        self,
        seg_data: dict,
        *,
        page_id: str,
    ) -> str:
        """Download image bytes and render via configured method (url/base64)."""
        url = self._segment_url(seg_data)
        if not url:
            return html.escape("[图片]")

        attachment = Attachment(
            type="image", url=url, name=self._segment_name(seg_data, "image.jpg")
        )
        result = await media.fetch_attachment(
            attachment,
            max_bytes=max(1, int(self.config.max_file_size or 10 * 1024 * 1024)),
            proxy=self._media_proxy,
        )
        if not result:
            # Download failed or oversized; show link with alt text
            safe_url = html.escape(url)
            return (
                f"<a href='{safe_url}' target='_blank' rel='noopener noreferrer'>"
                "<div class='fwd-image-placeholder'><span class='lang-zh'>图片未缓存 / 已过期 / 超过大小限制</span><span class='lang-en'>Image not cached / expired / too large</span></div>"
                f"</a>"
            )

        data, mime = result
        normalized_mime = (mime or "").split(";", 1)[0].strip().lower()
        if not self._is_safe_forward_image_mime(normalized_mime):
            safe_url = html.escape(url)
            return (
                f"<a href='{safe_url}' target='_blank' rel='noopener noreferrer'>"
                "<div class='fwd-image-placeholder'>"
                "<span class='lang-zh'>图片 MIME 类型不安全，已阻止内嵌预览</span>"
                "<span class='lang-en'>Image MIME type unsafe, embed preview blocked</span>"
                "</div>"
                f"</a>"
            )

        if self.config.forward_render_image_method == "base64":
            data_url = f"data:{normalized_mime};base64,{base64.b64encode(data).decode('ascii')}"
            safe_data_url = html.escape(data_url)
            return (
                f"<img class='fwd-image fwd-image-open' src='{safe_data_url}' "
                "loading='lazy' referrerpolicy='no-referrer' alt='Image'/>"
            )

        asset_id = str(uuid.uuid4())
        expires_at: int | None
        asset_ttl = self._effective_forward_asset_ttl()
        if asset_ttl > 0:
            expires_at = int(_utc_now().timestamp()) + asset_ttl
        else:
            expires_at = None

        msg_db().save_forward_asset(
            asset_id=asset_id,
            page_id=page_id,
            instance_id=self.instance_id,
            mime=normalized_mime,
            data=data,
            created_at=int(_utc_now().timestamp()),
            expires_at=expires_at,
        )

        asset_url = html.escape(self._build_forward_asset_url(asset_id))
        return (
            f"<a class='fwd-image-link' href='{asset_url}' target='_blank' rel='noopener noreferrer'>"
            f"<img class='fwd-image' src='{asset_url}' "
            "loading='lazy' referrerpolicy='no-referrer' alt='Image'/>"
            f"</a>"
        )

    @staticmethod
    def _parse_forward_file_size(seg_data: dict) -> int | None:
        raw_size = seg_data.get("file_size", seg_data.get("size", ""))
        try:
            size = int(raw_size)
            return size if size >= 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_size_human(size_bytes: int | None) -> str:
        if size_bytes is None:
            return "Unknown"
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(size_bytes)
        unit = units[0]
        for u in units:
            unit = u
            if value < 1024 or u == units[-1]:
                break
            value /= 1024.0
        if unit == "B":
            return f"{int(value)} {unit}"
        return f"{value:.2f} {unit}"

    async def _resolve_forward_file_download_url(
        self,
        *,
        file_id: str,
        source_group_id: str,
        busid: str | None = None,
    ) -> str:
        if not file_id:
            return ""

        if self.config.protocol == "onebot_v11":
            return ""

        cache_key = f"{source_group_id}:{file_id}"
        if cache_key in self._forward_file_url_cache:
            return self._forward_file_url_cache[cache_key] or ""

        action_candidates: list[tuple[str, dict]] = []
        group_id_num: int | None = None
        try:
            if source_group_id:
                group_id_num = int(source_group_id)
        except ValueError:
            group_id_num = None

        if group_id_num is not None:
            action_candidates.append(
                ("get_group_file_url", {"group_id": group_id_num, "file_id": file_id})
            )
        if source_group_id:
            params = {"group_id": source_group_id, "file_id": file_id}
            if busid not in (None, ""):
                params["busid"] = busid
            action_candidates.append(("get_group_file_url", params))
        action_candidates.append(("get_file", {"file_id": file_id}))

        for action, params in action_candidates:
            response = await self._call(action, params, timeout=12.0, retries=2)
            if not response or response.get("status") != "ok":
                continue

            data = response.get("data") or {}
            if not isinstance(data, dict):
                continue

            for key in ("url", "download_url", "file_url", "file"):
                candidate = str(data.get(key, "")).strip()
                if candidate.startswith(("http://", "https://")):
                    self._forward_file_url_cache[cache_key] = candidate
                    return candidate

        self.logger.debug(
            f"NapCat [{self.instance_id}] forward file download url unresolved for file_id={file_id}"
        )
        self._forward_file_url_cache[cache_key] = None
        return ""

    async def _resolve_record_attachment(self, seg_data: dict) -> Attachment:
        name = self._segment_name(seg_data, "voice.amr")
        self.logger.info(
            f"NapCat [{self.instance_id}] resolving voice attachment, "
            f"seg fields: {seg_data!r}"
        )

        candidates: list[str] = []
        for key in ("url", "path", "file", "name"):
            value = str(seg_data.get(key) or "").strip()
            if (
                value
                and not value.startswith(("http://", "https://"))
                and value not in candidates
            ):
                candidates.append(value)

        for file_ref in candidates:
            response = await self._call(
                "get_record",
                {"file": file_ref, "out_format": "amr"},
                timeout=10.0,
                retries=1,
            )
            self.logger.info(
                f"NapCat [{self.instance_id}] get_record({file_ref!r}) -> {response!r}"
            )
            data = (
                response.get("data")
                if response and response.get("status") == "ok"
                else None
            )
            if not isinstance(data, dict):
                continue

            b64 = str(data.get("base64") or "").strip()
            if b64.startswith("base64://"):
                b64 = b64[len("base64://") :]
            if b64:
                try:
                    raw = base64.b64decode(b64)
                except Exception:
                    raw = b""
                if raw:
                    file_name = str(data.get("file_name") or data.get("name") or name)
                    return Attachment(type="voice", url="", data=raw, name=file_name)

            url = self._segment_url(data)
            if url:
                return Attachment(
                    type="voice",
                    url=url,
                    name=self._segment_name(data, name),
                )

        self.logger.debug(
            f"NapCat [{self.instance_id}] get_record unresolved for voice {name!r}"
        )
        return Attachment(type="voice", url="", name=name)

    async def _render_forward_file_asset_html(
        self,
        seg_data: dict,
        *,
        source_group_id: str,
    ) -> str:
        raw_name = self._segment_name(seg_data, "file")
        name = html.escape(raw_name)
        file_id = str(seg_data.get("file_id", seg_data.get("id", ""))).strip()
        size_bytes = self._parse_forward_file_size(seg_data)
        size_text = self._format_size_human(size_bytes)
        file_id_text = html.escape(file_id or "Unknown")

        url = self._segment_url(seg_data)
        if not url and file_id:
            url = await self._resolve_forward_file_download_url(
                file_id=file_id,
                source_group_id=source_group_id,
                busid=str(seg_data.get("busid", seg_data.get("bus_id", ""))).strip(),
            )

        download_html = "<span class='asset file disabled'><span class='lang-zh'>暂无法下载</span><span class='lang-en'>Unavailable</span></span>"
        if url:
            safe_url = html.escape(url)
            download_html = (
                f"<a class='asset file' href='{safe_url}' "
                "target='_blank' rel='noopener noreferrer'>"
                f"<span class='lang-zh'>下载 {name}</span><span class='lang-en'>Download {name}</span></a>"
            )

        return (
            "<div class='file-block'>"
            "<span class='chip'>" + self._bilingual("文件", "File") + "</span>"
            f"<div class='file-name'>{name}</div>"
            f"<div class='file-meta'><span class='lang-zh'>大小: {size_text} · file_id: {file_id_text}</span><span class='lang-en'>Size: {size_text} · file_id: {file_id_text}</span></div>"
            f"{download_html}"
            "</div>"
        )

    @staticmethod
    def _forward_segment_nodes(seg_data: dict) -> list[dict]:
        for key in ("content", "messages", "message"):
            nodes = seg_data.get(key)
            if isinstance(nodes, list):
                return nodes
        return []

    @staticmethod
    def _extract_richheader(text: str) -> tuple[str, dict | None]:
        return parse_richheader_tag(text)

    @staticmethod
    def _forward_node_sender_fields(node: dict) -> tuple[str, str]:
        sender = node.get("sender") or {}

        user_id_candidates = (
            sender.get("user_id"),
            sender.get("uin"),
            sender.get("uid"),
            sender.get("sender_id"),
            sender.get("sender_uin"),
            sender.get("senderUin"),
            node.get("user_id"),
            node.get("uin"),
            node.get("uid"),
            node.get("sender_id"),
            node.get("sender_uin"),
            node.get("senderUin"),
        )

        nickname_candidates = (
            sender.get("nickname"),
            sender.get("card"),
            sender.get("name"),
            sender.get("nick"),
            node.get("nickname"),
            node.get("name"),
        )

        user_id = ""
        for candidate in user_id_candidates:
            value = str(candidate or "").strip()
            if value:
                user_id = value
                break

        nickname = ""
        for candidate in nickname_candidates:
            value = str(candidate or "").strip()
            if value:
                nickname = value
                break

        return user_id, (nickname or "Unknown")

    @staticmethod
    def _forward_node_message_id(node: dict) -> str:
        candidates = (
            node.get("message_id"),
            node.get("messageId"),
            node.get("msg_id"),
            node.get("msgId"),
            node.get("id"),
            node.get("seq"),
            node.get("message_seq"),
            node.get("real_id"),
            node.get("real_seq"),
        )

        data = node.get("data")
        if isinstance(data, dict):
            candidates += (
                data.get("message_id"),
                data.get("messageId"),
                data.get("msg_id"),
                data.get("msgId"),
                data.get("id"),
                data.get("seq"),
                data.get("message_seq"),
                data.get("real_id"),
                data.get("real_seq"),
            )

        for candidate in candidates:
            value = str(candidate or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _forward_node_time(node: dict) -> int:
        candidates = (
            node.get("time"),
            node.get("time_stamp"),
            node.get("timestamp"),
        )
        data = node.get("data")
        if isinstance(data, dict):
            candidates += (
                data.get("time"),
                data.get("time_stamp"),
                data.get("timestamp"),
            )
        for candidate in candidates:
            if candidate is None:
                continue
            try:
                val = int(candidate)
                if val > 0:
                    return val
            except (TypeError, ValueError):
                pass
        return 0

    @staticmethod
    def _forward_reply_target_id(seg_data: dict) -> str:
        candidates = (
            seg_data.get("id"),
            seg_data.get("message_id"),
            seg_data.get("messageId"),
            seg_data.get("msg_id"),
            seg_data.get("msgId"),
            seg_data.get("seq"),
            seg_data.get("message_seq"),
            seg_data.get("real_id"),
            seg_data.get("real_seq"),
        )

        for candidate in candidates:
            value = str(candidate or "").strip()
            if value:
                return value
        return ""

    def _resolve_forward_msg_format(self, source_group_id: str) -> str | None:
        if not source_group_id:
            return None

        rules = getattr(self.bridge, "_rules", [])
        for rule in rules:
            if not isinstance(rule, dict):
                continue

            msg_cfg = rule.get("msg")
            if not isinstance(msg_cfg, dict):
                continue

            fmt = msg_cfg.get("msg_format")
            if not isinstance(fmt, str) or not fmt.strip():
                continue

            if rule.get("type") == "connect":
                channels = rule.get("channels") or {}
                src = channels.get(self.instance_id)
                if isinstance(src, dict) and str(src.get("group_id", "")) == str(
                    source_group_id
                ):
                    return fmt
                continue

            from_cfg = rule.get("from") or {}
            src = from_cfg.get(self.instance_id)
            if isinstance(src, dict) and str(src.get("group_id", "")) == str(
                source_group_id
            ):
                return fmt

        return None

    def _apply_forward_msg_format_header(
        self,
        *,
        msg_format: str | None,
        nickname: str,
        user_id: str,
        msg_text: str,
    ) -> dict | None:
        if not msg_format:
            return None

        avatar = (
            f"https://q.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=160"
            if user_id
            else ""
        )
        ctx = {
            "platform": "qq",
            "instance_id": self.instance_id,
            "from": self.instance_id,
            "user": nickname,
            "user_id": user_id,
            "user_avatar": avatar,
            "msg": msg_text,
            "time": "",
            "username": user_id,
            "nickname": nickname,
        }

        try:
            formatted = msg_format.format(**ctx)
        except KeyError as exc:
            self.logger.debug(
                f"NapCat [{self.instance_id}] forward header msg_format missing key: {exc}"
            )
            return None

        _, richheader = self._extract_richheader(formatted)
        return richheader

    def _detect_unreliable_forward_user_ids(self, nodes: list[dict]) -> set[str]:
        """Detect sender IDs that map to multiple nicknames in one forward batch.

        Some NapCat versions may reuse a pseudo id for different forwarded senders.
        In such cases, using that ID for avatar/QQ display is misleading.
        """
        sender_uids = {
            uid
            for uid, _ in (self._forward_node_sender_fields(node) for node in nodes)
            if uid
        }
        if len(sender_uids) <= 1:
            # Single-sender forwards cannot be cross-validated inside the batch.
            # Mark as unreliable to avoid presenting UID as authoritative.
            return set(sender_uids)

        mapping: dict[str, set[str]] = {}
        for node in nodes:
            uid, nick = self._forward_node_sender_fields(node)
            if not uid:
                continue
            mapping.setdefault(uid, set()).add(nick or "Unknown")

        return {uid for uid, nicks in mapping.items() if len(nicks) > 1}

    @staticmethod
    def _format_duration_cn(seconds: int) -> str:
        seconds = max(0, int(seconds))
        days, rem = divmod(seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, secs = divmod(rem, 60)

        if days > 0:
            return f"{days}天{hours}小时{minutes}分{secs}秒"
        if hours > 0:
            return f"{hours}小时{minutes}分{secs}秒"
        if minutes > 0:
            return f"{minutes}分{secs}秒"
        return f"{secs}秒"

    @staticmethod
    def _format_duration_en(seconds: int) -> str:
        seconds = max(0, int(seconds))
        days, rem = divmod(seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, secs = divmod(rem, 60)

        parts: list[str] = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        parts.append(f"{secs}s")
        return " ".join(parts)

    @staticmethod
    def _bilingual(zh: str, en: str) -> str:
        return (
            "<span class='lang-zh'>"
            + html.escape(zh)
            + "</span><span class='lang-en'>"
            + html.escape(en)
            + "</span>"
        )

    def _unreliable_uid_label(self) -> str:
        return self._bilingual("UID 不可靠", "UID Unreliable")

    @staticmethod
    def _format_message_time(ts: int) -> str:
        if not ts:
            return ""
        dt = datetime.datetime.fromtimestamp(ts)
        now = datetime.datetime.now()

        # simple formatting: MM-DD HH:MM
        if dt.year == now.year:
            return dt.strftime("%m-%d %H:%M")
        return dt.strftime("%Y-%m-%d %H:%M")

    async def _render_forward_nodes_html(
        self,
        nodes: list[dict],
        *,
        source_group_id: str,
        page_id: str,
        depth: int = 0,
    ) -> str:
        rendered: list[str] = []
        node_items: list[dict[str, str]] = []
        node_index: dict[str, dict[str, str]] = {}
        msg_format = self._resolve_forward_msg_format(source_group_id)
        unreliable_user_ids = self._detect_unreliable_forward_user_ids(nodes)
        max_depth = 4

        for node in nodes:
            user_id, nickname = self._forward_node_sender_fields(node)
            message_id = self._forward_node_message_id(node)
            msg_time = self._forward_node_time(node)
            time_text = self._format_message_time(msg_time) if msg_time else ""
            time_hover = (
                datetime.datetime.fromtimestamp(msg_time).strftime("%Y-%m-%d %H:%M:%S")
                if msg_time
                else ""
            )

            richheader: dict | None = None
            reply_to_id = ""
            user_id_reliable = user_id not in unreliable_user_ids

            # if not user_id_reliable and user_id:
            #     self.logger.debug(
            #         f"NapCat [{self.instance_id}] forward node user_id marked unreliable: {user_id}"
            #     )

            # self.logger.debug(
            #     f"NapCat [{self.instance_id}] forward node sender resolved "
            #     f"nickname={nickname!r} user_id={user_id!r} "
            #     f"raw_sender={node.get('sender')!r}"
            # )

            content = node.get("content")
            if content is None:
                content = node.get("message")
            if content is None and isinstance(node.get("data"), dict):
                content = node["data"].get("content") or node["data"].get("message")

            content_parts: list[str] = []
            plain_text_parts: list[str] = []
            for seg in content if isinstance(content, list) else []:
                seg_type = seg.get("type", "")
                seg_data = seg.get("data") or {}

                if seg_type == "text":
                    raw_text = str(seg_data.get("text", ""))
                    clean_text, parsed = self._extract_richheader(raw_text)
                    if parsed and richheader is None:
                        richheader = parsed
                    if clean_text:
                        plain_text_parts.append(clean_text)
                        content_parts.append(html.escape(clean_text))
                elif seg_type == "at":
                    qq = str(seg_data.get("qq", ""))
                    name = seg_data.get("name") or qq
                    plain_text_parts.append(f"@{name}")
                    content_parts.append(html.escape(f"@{name}"))
                elif seg_type == "image":
                    content_parts.append(
                        await self._render_forward_image_asset_html(
                            seg_data,
                            page_id=page_id,
                        )
                    )
                elif seg_type == "record":
                    content_parts.append(
                        await self._render_forward_voice_asset_html(seg_data)
                    )
                elif seg_type == "video":
                    content_parts.append(
                        self._render_forward_asset_html(
                            seg_data,
                            kind_label=self._bilingual("视频", "Video"),
                            kind_class="video",
                            fallback_name="video.mp4",
                        )
                    )
                elif seg_type == "file":
                    content_parts.append(
                        await self._render_forward_file_asset_html(
                            seg_data,
                            source_group_id=source_group_id,
                        )
                    )
                elif seg_type == "forward":
                    nested_nodes = self._forward_segment_nodes(seg_data)
                    if nested_nodes and depth < max_depth:
                        content_parts.append(
                            await self._render_forward_nested_html(
                                nested_nodes,
                                source_group_id=source_group_id,
                                page_id=page_id,
                                depth=depth + 1,
                            )
                        )
                    else:
                        plain_text_parts.append("Forward")
                        content_parts.append(self._bilingual("合并转发", "Forward"))
                elif seg_type == "reply":
                    reply_to_id = self._forward_reply_target_id(seg_data)
                elif seg_type == "face":
                    content_parts.append(
                        self._render_forward_face_segment_html(seg_data)
                    )
                elif seg_type == "mface":
                    # Multimedia face (emoji): try to render as image first, fall back to summary text
                    summary = str(seg_data.get("summary", "")).strip()
                    image_html = await self._render_forward_image_asset_html(
                        seg_data,
                        page_id=page_id,
                    )
                    # Check if image was successfully rendered in either url/base64 mode
                    if "class='fwd-image" in image_html:
                        content_parts.append(image_html)
                    elif summary:
                        plain_text_parts.append(summary)
                        content_parts.append(html.escape(summary))
                    else:
                        plain_text_parts.append("Sticker")
                        content_parts.append(self._bilingual("表情", "Sticker"))

            if richheader is None:
                msg_text = "".join(plain_text_parts).strip()
                richheader = self._apply_forward_msg_format_header(
                    msg_format=msg_format,
                    nickname=nickname,
                    user_id=user_id,
                    msg_text=msg_text,
                )

            message_html = "".join(content_parts).strip() or self._bilingual(
                "空消息", "Empty"
            )
            message_text = "".join(plain_text_parts).strip() or "[空消息]"
            default_sender = f"{nickname}" + (f" ({user_id})" if user_id else "")
            if user_id and not user_id_reliable:
                default_sender += f" [{self._unreliable_uid_label()}]"

            header_title_raw = (
                str(richheader.get("title", "")).strip() if richheader else ""
            )
            header_content_raw = (
                str(richheader.get("content", "")).strip() if richheader else ""
            )
            if user_id and not user_id_reliable and richheader:
                if user_id not in header_content_raw:
                    header_content_raw = (
                        f"QQ: {user_id} · {header_content_raw}"
                        if header_content_raw
                        else f"QQ: {user_id}"
                    )
                header_content_raw = (
                    f"{header_content_raw} · UID 不可靠"
                    if header_content_raw
                    else "UID 不可靠"
                )

            header_title = html.escape(header_title_raw) or html.escape(default_sender)
            header_content = html.escape(header_content_raw)

            avatar_url = ""
            if richheader:
                avatar_url = str(richheader.get("avatar", "")).strip()
            if not avatar_url and user_id and user_id_reliable:
                avatar_url = f"https://q.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=160"

            avatar_html = ""
            if avatar_url.startswith(("http://", "https://")):
                avatar_html = (
                    "<div class='avatar-wrapper'>"
                    f"<img class='avatar' src='{html.escape(avatar_url)}' "
                    "alt='avatar' referrerpolicy='no-referrer' loading='lazy'/>"
                    "</div>"
                )
            else:
                avatar_html = "<div class='avatar-wrapper'></div>"

            hover_parts = []
            if user_id:
                hover_parts.append(
                    f"UID: {user_id}"
                    if user_id_reliable
                    else f"UID: {user_id} (UID 不可靠)"
                )
            if time_hover:
                hover_parts.append(time_hover)
            hover_text = " · ".join(hover_parts)
            hover_html = f" title='{html.escape(hover_text)}'" if hover_text else ""

            # Use span with title inside header_title for hover
            header_title_html = f"<span{hover_html}>{header_title}</span>"
            if time_text:
                header_title_html += (
                    f"<span class='msg-time'>{html.escape(time_text)}</span>"
                )

            header_content_html = (
                f"<div class='sender-sub'>{header_content}</div>"
                if header_content
                else ""
            )
            item = {
                "message_id": message_id,
                "reply_to_id": reply_to_id,
                "default_sender": default_sender,
                "header_title": header_title_html,
                "message_text": message_text,
                "avatar_html": avatar_html,
                "header_content_html": header_content_html,
                "message_html": message_html,
            }
            node_items.append(item)
            if message_id and message_id not in node_index:
                node_index[message_id] = item

        for item in node_items:
            reply_html = ""
            reply_to_id = item.get("reply_to_id", "")
            if reply_to_id:
                reply_html = (
                    "<blockquote class='reply-preview'>"
                    "<div class='reply-preview-title'>"
                    + self._bilingual("回复消息", "Reply")
                    + "</div>"
                    "</blockquote>"
                )

            rendered.append(
                "<article class='msg'>"
                f"{item.get('avatar_html', '')}"
                "<div class='sender-meta'>"
                f"<div class='sender-main'>{item.get('header_title', '')}</div>"
                f"{item.get('header_content_html', '')}"
                "<div class='content-wrapper'>"
                f"{reply_html}"
                f"<div class='content'>{item.get('message_html', '')}</div>"
                "</div>"
                "</div>"
                "</article>"
            )

        return "\n".join(rendered)

    async def _render_forward_nested_html(
        self,
        nodes: list[dict],
        *,
        source_group_id: str,
        page_id: str,
        depth: int,
    ) -> str:
        nested_body = await self._render_forward_nodes_html(
            nodes,
            source_group_id=source_group_id,
            page_id=page_id,
            depth=depth,
        )
        return (
            "<details class='nested-forward'>"
            "<summary class='nested-forward-title'>"
            + self._bilingual("展开嵌套合并转发", "Expand Nested Forward")
            + "</summary>"
            f"<div class='nested-forward-body'>{nested_body}</div>"
            "</details>"
        )

    def _render_forward_page_html(
        self,
        title: str,
        body_html: str,
        meta_primary_text: str,
        meta_secondary_text: str,
        meta_attachment_text: str,
        *,
        created_at: datetime.datetime,
        expires_at: datetime.datetime,
        destroyed_at: datetime.datetime | None = None,
    ) -> str:
        title_html = self._bilingual("QQ 合并转发消息", "QQ Combined Forward")
        meta_primary_html = meta_primary_text
        meta_secondary_html = meta_secondary_text
        meta_attachment_html = meta_attachment_text
        page_state = "destroyed" if destroyed_at is not None else "active"
        page_state_text = (
            self._bilingual("已销毁", "Destroyed")
            if destroyed_at is not None
            else self._bilingual("有效", "Active")
        )
        return _get_forward_page_template().substitute(
            title=title,
            title_html=title_html,
            meta_primary=meta_primary_html,
            meta_secondary=meta_secondary_html,
            meta_attachment=meta_attachment_html,
            created_at_epoch=str(int(created_at.timestamp())),
            expires_at_epoch=str(int(expires_at.timestamp())),
            destroyed_at_epoch=str(int(destroyed_at.timestamp()))
            if destroyed_at
            else "",
            page_state=page_state,
            page_state_text=page_state_text,
            body=body_html,
        )

    async def _render_forward_segment(
        self,
        seg_data: dict,
        *,
        source_group_id: str,
    ) -> str:
        if not self.config.forward_render_enabled or not self._supports_forward_api():
            return "[Forwarded messages]"

        forward_id = str(seg_data.get("id", "")).strip()
        if not forward_id:
            return "[Forwarded messages]"

        self.logger.debug(
            f"NapCat [{self.instance_id}] rendering forward segment id={forward_id}"
        )

        payload = await self._api_get_forward_msg(forward_id)
        if not payload:
            self.logger.warning(
                f"NapCat [{self.instance_id}] get_forward_msg failed for id={forward_id}"
            )
            return "[Forwarded messages]"

        nodes = payload.get("messages")
        if nodes is None:
            nodes = payload.get("message")
        if not isinstance(nodes, list):
            self.logger.warning(
                f"NapCat [{self.instance_id}] get_forward_msg no messages for id={forward_id}"
            )
            return "[Forwarded messages]"

        page_id = str(uuid.uuid4())
        body_html = await self._render_forward_nodes_html(
            nodes,
            source_group_id=source_group_id,
            page_id=page_id,
        )
        created_at = _utc_now()
        created_at_ts = int(created_at.timestamp())
        ttl = self._effective_forward_ttl(source_group_id)
        expires_at = created_at + datetime.timedelta(seconds=ttl)
        expires_at_ts = int(expires_at.timestamp())
        meta_primary_text = (
            f"<span class='lang-zh'>生成于 {created_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %z')}</span>"
            f"<span class='lang-en'>Generated at {created_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %z')}</span>"
        )
        meta_secondary_text = (
            f"<span class='lang-zh'>有效期至 {expires_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %z')}</span>"
            f"<span class='lang-en'>Expires at {expires_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %z')}</span>"
        )
        asset_ttl = self._effective_forward_asset_ttl()
        if asset_ttl > 0:
            asset_expires_at = created_at + datetime.timedelta(seconds=asset_ttl)
            cn_dur = self._format_duration_cn(asset_ttl)
            en_dur = self._format_duration_en(asset_ttl)
            meta_attachment_text = (
                f"<span class='lang-zh'>附件有效期至 {asset_expires_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %z')} "
                f"（约 {cn_dur}）</span>"
                f"<span class='lang-en'>Attachments expire at {asset_expires_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %z')} "
                f"(approx. {en_dur})</span>"
            )
        else:
            meta_attachment_text = ""
        page_html = self._render_forward_page_html(
            title="QQ 合并转发消息",
            body_html=body_html,
            meta_primary_text=meta_primary_text,
            meta_secondary_text=meta_secondary_text,
            meta_attachment_text=meta_attachment_text,
            created_at=created_at,
            expires_at=expires_at,
        )

        self._forward_pages[page_id] = _ForwardPage(
            html_content=page_html,
            created_at=created_at,
            expires_at=expires_at,
        )
        if self.config.forward_render_persist_enabled:
            msg_db().save_forward_page(
                page_id=page_id,
                instance_id=self.instance_id,
                html_content=page_html,
                created_at=created_at_ts,
                expires_at=expires_at_ts,
            )

        link = self._build_forward_page_url(page_id)
        return f"[QQ Combined Forward / 合并转发] {link}"

    # ------------------------------------------------------------------
    # Action helpers
    # ------------------------------------------------------------------

    def _resolve_send_mode(self, size: int) -> str:
        """
        Return the effective file/video send mode for a payload of *size* bytes.
        Forces \"stream\" when stream_threshold is set and size exceeds it.
        """
        if self.config.stream_threshold > 0 and size > self.config.stream_threshold:
            return "stream"
        return self.config.file_send_mode

    async def _call(
        self,
        action: str,
        params: dict,
        timeout: float = 30.0,
        retries: int = 0,
    ) -> dict | None:
        """Send a OneBot action and await its echo response."""
        if self._ws is None:
            return None
        max_attempts = max(1, int(retries) + 1)

        for attempt in range(1, max_attempts + 1):
            echo = str(uuid.uuid4())
            fut: asyncio.Future = asyncio.get_event_loop().create_future()
            self._pending[echo] = fut
            payload = {"action": action, "params": params, "echo": echo}
            try:
                async with self._send_lock:
                    await self._ws.send(json.dumps(payload, ensure_ascii=False))
                return await asyncio.wait_for(fut, timeout=timeout)
            except TimeoutError:
                self._pending.pop(echo, None)
                if attempt >= max_attempts:
                    self.logger.warning(
                        f"NapCat [{self.instance_id}] action '{action}' timed out "
                        f"after {attempt} attempt(s)"
                    )
                    return None
                self.logger.warning(
                    f"NapCat [{self.instance_id}] action '{action}' timed out, "
                    f"retrying ({attempt}/{max_attempts - 1})"
                )
                await asyncio.sleep(min(2.0, 0.3 * (2 ** (attempt - 1))))
            except Exception as e:
                self._pending.pop(echo, None)
                if attempt >= max_attempts:
                    self.logger.error(
                        f"NapCat [{self.instance_id}] action '{action}' error "
                        f"after {attempt} attempt(s): {e}"
                    )
                    return None
                self.logger.warning(
                    f"NapCat [{self.instance_id}] action '{action}' error, "
                    f"retrying ({attempt}/{max_attempts - 1}): {e}"
                )
                await asyncio.sleep(min(2.0, 0.3 * (2 ** (attempt - 1))))

        return None

    async def _api_send_group_msg(
        self, group_id, message, *, timeout: float = 30.0
    ) -> str | None:
        """Send a group message via OneBot. Returns ``message_id`` on success or ``None``."""
        resp = await self._call(
            "send_group_msg",
            {"group_id": int(group_id), "message": message},
            timeout=timeout,
        )
        if resp and resp.get("status") == "ok":
            data = resp.get("data") or {}
            if "message_id" in data:
                return str(data["message_id"])
        return None

    async def _api_send_private_msg(
        self, user_id, message, *, timeout: float = 30.0
    ) -> str | None:
        """Send a private message via OneBot. Returns ``message_id`` on success or ``None``."""
        resp = await self._call(
            "send_private_msg",
            {"user_id": int(user_id), "message": message},
            timeout=timeout,
        )
        if resp and resp.get("status") == "ok":
            data = resp.get("data") or {}
            if "message_id" in data:
                return str(data["message_id"])
        return None

    async def _api_set_essence_msg(
        self, message_id, group_id, *, timeout: float = 30.0
    ) -> bool:
        resp = await self._call(
            "set_essence_msg",
            {"message_id": int(message_id), "group_id": int(group_id)},
            timeout=timeout,
        )
        return bool(resp and resp.get("status") == "ok")

    async def _api_delete_essence_msg(
        self, message_id, group_id, *, timeout: float = 30.0
    ) -> bool:
        resp = await self._call(
            "delete_essence_msg",
            {"message_id": int(message_id), "group_id": int(group_id)},
            timeout=timeout,
        )
        return bool(resp and resp.get("status") == "ok")

    async def _api_get_essence_msg_list(
        self, group_id, *, timeout: float = 30.0
    ) -> list[dict]:
        resp = await self._call(
            "get_essence_msg_list",
            {"group_id": int(group_id)},
            timeout=timeout,
        )
        if resp and resp.get("status") == "ok":
            return (
                (resp.get("data") or []) if isinstance(resp.get("data"), list) else []
            )
        return []

    async def _api_delete_msg(self, message_id, *, timeout: float = 30.0) -> bool:
        """Recall a message via OneBot ``delete_msg``. Returns True on success."""
        resp = await self._call(
            "delete_msg",
            {"message_id": int(message_id)},
            timeout=timeout,
        )
        return bool(resp and resp.get("status") == "ok")

    async def _api_get_group_member_info(
        self, group_id, user_id, *, no_cache: bool = False
    ) -> dict | None:
        """Fetch group member info via OneBot. Returns the ``data`` dict or ``None``."""
        resp = await self._call(
            "get_group_member_info",
            {"group_id": int(group_id), "user_id": int(user_id), "no_cache": no_cache},
        )
        if resp and resp.get("status") == "ok":
            return resp.get("data") or {}
        return None

    async def _api_get_stranger_info(self, user_id) -> dict | None:
        """Fetch stranger info via OneBot. Returns the ``data`` dict or ``None``."""
        resp = await self._call(
            "get_stranger_info",
            {"user_id": user_id},
            timeout=30.0,
            retries=2,
        )
        if resp and resp.get("status") == "ok":
            return resp.get("data") or {}
        return None

    async def _api_get_forward_msg(self, forward_id) -> dict | None:
        """Fetch forward message chain via OneBot. Returns the ``data`` dict or ``None``."""
        resp = await self._call(
            "get_forward_msg",
            {"id": forward_id},
            timeout=30.0,
            retries=2,
        )
        if resp and resp.get("status") == "ok":
            return resp.get("data") or {}
        return None

    async def _api_get_group_file_url(self, group_id, file_id, busid) -> str | None:
        """Resolve a group file download URL. Tries ``get_group_file_url`` and ``get_file``."""
        resp = await self._call(
            "get_group_file_url",
            {"group_id": int(group_id), "file_id": str(file_id), "busid": busid},
            timeout=20.0,
        )
        if resp and resp.get("status") == "ok":
            data = resp.get("data") or {}
            for key in ("url", "download_url", "file_url", "file"):
                candidate = str(data.get(key, "")).strip()
                if candidate.startswith(("http://", "https://")):
                    return candidate
        resp = await self._call(
            "get_file",
            {"file_id": str(file_id)},
            timeout=20.0,
        )
        if resp and resp.get("status") == "ok":
            data = resp.get("data") or {}
            for key in ("url", "download_url", "file_url", "file"):
                candidate = str(data.get(key, "")).strip()
                if candidate.startswith(("http://", "https://")):
                    return candidate
        return None

    async def _get_qid(self, user_id: str, group_id: str | None = None) -> str:
        """Get user's qid using NapCat API with caching."""
        if user_id in self._qid_cache:
            return self._qid_cache[user_id]

        now = time.monotonic()
        last_miss = self._qid_miss_cache.get(user_id)
        if last_miss is not None and now - last_miss < 300:
            return ""

        try:
            data = await self._api_get_stranger_info(user_id)
            if data:
                qid = data.get("qid", "")
                if qid:
                    self._qid_cache[user_id] = qid
                else:
                    self._qid_miss_cache[user_id] = now
                self.logger.debug(f"qid for {user_id}: {qid}")
                return qid
        except Exception as e:
            self._qid_miss_cache[user_id] = now
            self.logger.warning(
                f"NapCat [{self.instance_id}] failed to get qid for {user_id}: {e}"
            )
        return ""

    async def _upload_file_stream(self, data_bytes: bytes, filename: str) -> str | None:
        """
        Upload bytes via OneBot upload_file_stream (chunked base64).

        QQ-compatible OneBot implementations process chunk_data and is_complete in separate branches:
        when chunk_data is present it stores the chunk and returns early,
        so is_complete must be sent as a separate final request with no chunk_data.

        Returns the server-side file_path on success, or None on failure.
        """
        CHUNK_SIZE = 256 * 1024  # 256 KB per chunk
        total = len(data_bytes)
        total_chunks = max(1, math.ceil(total / CHUNK_SIZE))
        stream_id = str(uuid.uuid4())

        # Upload all chunks (the stream API expects "filename", not "file_name")
        for i in range(total_chunks):
            chunk = data_bytes[i * CHUNK_SIZE : (i + 1) * CHUNK_SIZE]
            b64 = base64.b64encode(chunk).decode()

            resp = await self._call(
                "upload_file_stream",
                {
                    "stream_id": stream_id,
                    "filename": filename,
                    "chunk_index": i,
                    "total_chunks": total_chunks,
                    "chunk_data": b64,
                },
            )
            if resp is None:
                self.logger.warning(
                    f"NapCat [{self.instance_id}] stream upload chunk {i}/{total_chunks} "
                    f"got no response for '{filename}'"
                )
                return None
            if resp.get("status") == "failed":
                self.logger.warning(
                    f"NapCat [{self.instance_id}] stream upload failed at chunk "
                    f"{i}/{total_chunks}: {resp.get('msg', '')}"
                )
                return None

        # Trigger completion in a separate request (is_complete + no chunk_data)
        resp = await self._call(
            "upload_file_stream",
            {
                "stream_id": stream_id,
                "is_complete": True,
            },
        )
        if resp is None or resp.get("status") == "failed":
            self.logger.warning(
                f"NapCat [{self.instance_id}] stream upload completion failed "
                f"for '{filename}': {resp}"
            )
            return None

        data = resp.get("data") or {}
        file_path = data.get("file_path")
        if not file_path:
            self.logger.warning(
                f"NapCat [{self.instance_id}] stream upload complete but "
                f"no file_path in response: {resp}"
            )
            return None

        return file_path

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
        group_id = channel.get("group_id")
        user_id = channel.get("user_id")
        if not group_id and not user_id:
            self.logger.warning(
                f"NapCat [{self.instance_id}] send: no group_id or user_id in channel {channel}"
            )
            return None

        if self._ws is None:
            self.logger.warning(
                f"NapCat [{self.instance_id}] send: not connected, message dropped"
            )
            return None

        is_group = bool(group_id)
        assert group_id or user_id

        async def _send_msg(segments):
            if is_group:
                return await self._api_send_group_msg(group_id, segments)
            return await self._api_send_private_msg(user_id, segments)

        segments: list[dict] = []
        msg_ids: list[str] = []
        deferred_file_uploads = []

        reply_to_id = kwargs.get("reply_to_id")
        if reply_to_id:
            segments.append({"type": "reply", "data": {"id": str(reply_to_id)}})

        rich_header = kwargs.get("rich_header")
        # Video/Record cannot be mixed with text in QQ, so if there are such attachments,
        # we still want to make sure the header goes with the text, but the whole text
        # message must be sent separately from the video/record message.
        # We will handle the separation later, so we just prepend the header to the text if there is text.
        # If there is NO text but there ARE non-image attachments, we send the header separately.
        has_non_image_attachments = any(
            att.type != "image"
            for att in (attachments or [])
            if att.url or att.data is not None
        )
        send_header_separately = bool(
            rich_header and has_non_image_attachments and not str(text or "").strip()
        )
        if rich_header:
            if not send_header_separately:
                t, c = rich_header.get("title", ""), rich_header.get("content", "")
                prefix = f"[{t}" + (f" · {c}" if c else "") + "]"
                text = f"{prefix}\n{text}" if text else prefix
            else:
                t, c = rich_header.get("title", ""), rich_header.get("content", "")
                prefix = f"[{t}" + (f" · {c}" if c else "") + "]"
                msg_id = await _send_msg([{"type": "text", "data": {"text": prefix}}])
                if not msg_id:
                    self.logger.warning(
                        f"NapCat [{self.instance_id}] failed to send standalone rich header "
                        f"before media message"
                    )
                else:
                    msg_ids.append(msg_id)

        # Process mentions: replace @Name with at segments
        mentions = kwargs.get("mentions", [])
        # We process text by splitting it at @mentions to insert segments properly
        if mentions and text:
            # Simple approach: if name is in text, replace and split
            # A more robust way is to build segments array carefully
            # For now, let's stick to the segments array logic
            pass

        if text:
            # We'll build segments by parsing the text for mentions
            last_idx = 0
            # Sort mentions by their position in text to process linearly
            # (In this bridge, we assume name matches exactly @name)
            for m in mentions:
                mention_str = f"@{m['name']}"
                idx = text.find(mention_str, last_idx)
                if idx != -1:
                    # Add preceding text
                    if idx > last_idx:
                        segments.append(
                            {"type": "text", "data": {"text": text[last_idx:idx]}}
                        )
                    # Add mention segment (converted to text in private chats)
                    if is_group:
                        segments.append({"type": "at", "data": {"qq": m["id"]}})
                    else:
                        segments.append({"type": "text", "data": {"text": mention_str}})
                    last_idx = idx + len(mention_str)

            # Add remaining text
            if last_idx < len(text):
                segments.append({"type": "text", "data": {"text": text[last_idx:]}})

        source_proxy = self._source_proxy_from_kwargs(kwargs)
        for att in attachments or []:
            if not att.url and att.data is None:
                continue

            match att.type:
                case "image":
                    result = await media.fetch_attachment(
                        att, self.config.max_file_size, source_proxy
                    )
                    if result:
                        data_bytes, _ = result
                        b64 = base64.b64encode(data_bytes).decode()
                        segments.append(
                            {"type": "image", "data": {"file": f"base64://{b64}"}}
                        )
                    else:
                        segments.append(
                            {
                                "type": "text",
                                "data": {"text": f"\n[图片: {att.name}]"},
                            }
                        )

                case "voice":
                    result = await media.fetch_attachment(
                        att, self.config.max_file_size, source_proxy
                    )
                    if result:
                        data_bytes, _ = result
                        b64 = base64.b64encode(data_bytes).decode()
                        segments.append(
                            {"type": "record", "data": {"file": f"base64://{b64}"}}
                        )
                    else:
                        segments.append(
                            {
                                "type": "text",
                                "data": {"text": f"\n[语音: {att.name}]"},
                            }
                        )

                case "video":
                    result = await media.fetch_attachment(
                        att, self.config.max_file_size, source_proxy
                    )
                    if result:
                        data_bytes, _ = result
                        mode = self._resolve_send_mode(len(data_bytes))
                        if mode == "base64":
                            b64 = base64.b64encode(data_bytes).decode()
                            segments.append(
                                {"type": "video", "data": {"file": f"base64://{b64}"}}
                            )
                        else:  # stream
                            file_path = await self._upload_file_stream(
                                data_bytes, att.name or "video.mp4"
                            )
                            if file_path:
                                segments.append(
                                    {"type": "video", "data": {"file": file_path}}
                                )
                            else:
                                segments.append(
                                    {
                                        "type": "text",
                                        "data": {"text": f"\n[视频: {att.name}]"},
                                    }
                                )
                    else:
                        segments.append(
                            {
                                "type": "text",
                                "data": {"text": f"\n[视频: {att.name}]"},
                            }
                        )

                case _:  # file
                    result = await media.fetch_attachment(
                        att, self.config.max_file_size, source_proxy
                    )
                    if result:
                        data_bytes, _ = result
                        fname = att.name or "file"

                        async def _do_upload(d=data_bytes, fn=fname, is_grp=is_group):
                            if is_grp:
                                assert group_id is not None
                                upload_api = "upload_group_file"
                                id_key = "group_id"
                                id_val = int(group_id)
                            else:
                                assert user_id is not None
                                upload_api = "upload_private_file"
                                id_key = "user_id"
                                id_val = int(user_id)

                            if self._supports_stream_file_upload():
                                mode = self._resolve_send_mode(len(d))
                                if mode == "base64":
                                    b64 = base64.b64encode(d).decode()
                                    await self._call(
                                        upload_api,
                                        {
                                            id_key: id_val,
                                            "file": f"base64://{b64}",
                                            "name": fn,
                                        },
                                    )
                                else:  # stream (default)
                                    file_path = await self._upload_file_stream(d, fn)
                                    if file_path:
                                        await self._call(
                                            upload_api,
                                            {
                                                id_key: id_val,
                                                "file": file_path,
                                                "name": fn,
                                            },
                                        )
                                    else:
                                        await _send_msg(
                                            [
                                                {
                                                    "type": "text",
                                                    "data": {
                                                        "text": f"\n[文件发送失败: {fn}]"
                                                    },
                                                }
                                            ],
                                        )
                            else:
                                if not await self._upload_file_from_bytes(
                                    d,
                                    fn,
                                    str(id_val),
                                    upload_api=upload_api,
                                    id_key=id_key,
                                ):
                                    await _send_msg(
                                        [
                                            {
                                                "type": "text",
                                                "data": {
                                                    "text": f"\n[文件发送失败: {fn}]"
                                                },
                                            }
                                        ],
                                    )

                        deferred_file_uploads.append(_do_upload)
                    else:
                        segments.append(
                            {
                                "type": "text",
                                "data": {"text": f"\n[文件: {att.name}]"},
                            }
                        )

        main_segments: list[dict] = []
        standalone_segments: list[dict | list[dict]] = []
        for seg in segments:
            if seg["type"] in ("video", "record"):
                standalone_segments.append(seg)
            else:
                main_segments.append(seg)

        if main_segments:
            if (
                len(main_segments) == 1
                and main_segments[0]["type"] == "reply"
                and standalone_segments
            ):
                # If only reply segment remains, attach it to the first standalone segment
                standalone_segments[0] = [
                    main_segments[0],
                    standalone_segments[0],
                ]  # ty: ignore[invalid-assignment]
                main_segments = []
            else:
                msg_id = await _send_msg(main_segments)
                if msg_id:
                    msg_ids.append(msg_id)

        for seg in standalone_segments:
            msg_to_send = seg if isinstance(seg, list) else [seg]
            msg_id = await _send_msg(msg_to_send)
            if msg_id:
                msg_ids.append(msg_id)

        for upload_func in deferred_file_uploads:
            await upload_func()

        return msg_ids if msg_ids else None

    async def edit(self, channel: dict, message_id: str, text: str, **kwargs):
        """Bridge an edit from another platform onto QQ.

        QQ (OneBot 11) has no native "edit message" API, so an edit cannot be
        applied in place. Instead we simulate it by sending a NEW message that
        quotes (replies to) the original bridged message and prepends
        ``edit_prefix`` so it is visually distinguishable from a normal message.
        """
        if not self.config.edit_via_reply:
            return None

        prefix = (self.config.edit_prefix or "").strip()
        body = text or ""
        if prefix:
            new_text = f"{prefix} {body}" if body else prefix
        else:
            new_text = body

        # Reply to the original bridged message so the edit is shown in context.
        # Do not mutate the caller's kwargs; strip any attachments the editor
        # path does not carry.
        send_kwargs = {k: v for k, v in kwargs.items() if k != "attachments"}
        send_kwargs["reply_to_id"] = message_id

        return await self.send(channel, new_text, **send_kwargs)

    async def pin(self, channel: dict, target_msg_id: str):
        group_id = channel.get("group_id")
        if not group_id:
            self.logger.debug("pin: no group_id in channel")
            return
        try:
            ok = await self._api_set_essence_msg(target_msg_id, group_id)
            if not ok:
                self.logger.warning(
                    f"NapCat [{self.instance_id}] failed to pin message {target_msg_id}"
                )
        except Exception as e:
            self.logger.warning(f"pin: failed to pin message {target_msg_id}: {e}")

    async def unpin(self, channel: dict, target_msg_id: str):
        group_id = channel.get("group_id")
        if not group_id:
            self.logger.debug("unpin: no group_id in channel")
            return
        try:
            ok = await self._api_delete_essence_msg(target_msg_id, group_id)
            if not ok:
                self.logger.warning(
                    f"NapCat [{self.instance_id}] failed to unpin message {target_msg_id}"
                )
        except Exception as e:
            self.logger.warning(f"unpin: failed to unpin message {target_msg_id}: {e}")

    async def delete(self, channel: dict, message_id: str, **kwargs):
        """Bridge a recall from another platform onto QQ via ``delete_msg``."""
        if not self.config.enable_recall:
            return None
        if not message_id:
            return None

        # Suppress the recall notice NapCat will echo back for this deletion so
        # we don't treat our own action as a new recall to bridge.
        self._recall_suppress.add(str(message_id))
        try:
            ok = await self._api_delete_msg(message_id)
        except Exception:
            self._recall_suppress.discard(str(message_id))
            raise
        if not ok:
            self.logger.warning(
                f"NapCat [{self.instance_id}] failed to recall message {message_id}"
            )
        return ok


register("qq", QqConfig, QqDriver)
