# QQ driver via NapCat (OneBot 11 WebSocket protocol).
# NapCat acts as a WebSocket server; this driver connects as a client,
# receives push events, and sends actions over the same connection.
#
# Config keys (under napcat.<instance_id>):
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
import re
import secrets
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Any, Literal

import websockets
import websockets.exceptions
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

import services.logger as log
from drivers import BaseDriver
from drivers.registry import register
from services import cqface, media
from services.config import UNSET, get_proxy
from services.config_schema import _DriverConfig
from services.db import msg_db
from services.message import Attachment, NormalizedMessage


class NapCatConfig(_DriverConfig):
    ws_url: str = "ws://127.0.0.1:3001"
    ws_token: str = ""
    max_file_size: int = 10 * 1024 * 1024
    file_send_mode: Literal["stream", "base64"] = "stream"
    cqface_mode: Literal["gif", "emoji"] = "gif"
    stream_threshold: int = 0
    forward_render_enabled: bool = False
    forward_render_ttl_seconds: int = 86400
    forward_render_mount_path: str = "/napcat-forward"
    forward_render_persist_enabled: bool = False
    forward_assets_base_url: str = ""
    # Merged-forward face rendering strategy:
    # - false: render by cqface mapping (unicode)
    # - true/unset: render by default gif host
    # - string: use custom gif host base URL
    forward_render_cqface_gif: bool | str = True
    proxy: str | None = UNSET


logger = log.get_logger()

_DEFAULT_FORWARD_CQFACE_GIF_HOST: str = "https://nextbridge.siiway.org/db/cqface-gif/"
_FORWARD_TEMPLATE_PATH: Path = (
    Path(__file__).resolve().parent.parent
    / "templates"
    / "napcat_forward_template.html"
)
_RICHHEADER_RE = re.compile(r"<richheader\b([^/]*)/>", re.IGNORECASE)
_RICHHEADER_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')

_FORWARD_PAGE_TEMPLATE = Template(
    """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /><title>$title</title></head>
<body><main><h1>$title</h1><div>$meta_primary</div><div>$meta_secondary</div>$body</main></body>
</html>"""
)


@lru_cache(maxsize=1)
def _get_forward_page_template() -> Template:
    try:
        text = _FORWARD_TEMPLATE_PATH.read_text(encoding="utf-8")
        return Template(text)
    except OSError as exc:
        logger.warning(
            f"Failed to load forward template {_FORWARD_TEMPLATE_PATH}: {exc}"
        )
        return _FORWARD_PAGE_TEMPLATE


@dataclass(slots=True)
class _ForwardPage:
    token: str
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
        logger.warning(f"Invalid face ID {face_id_raw!r} — ignored")
        return None

    candidate = (_FACE_DB / f"{face_id}.gif").resolve()

    # Layer 2 path-traversal guard.
    if not candidate.is_relative_to(_FACE_DB):
        logger.warning(f"Face path {candidate} escapes database dir — blocked")
        return None

    if not candidate.is_file():
        return None

    try:
        return candidate.read_bytes()
    except OSError as e:
        logger.error(f"Failed to read face GIF {candidate}: {e}")
        return None


class NapCatDriver(BaseDriver[NapCatConfig]):
    def __init__(self, instance_id: str, config: NapCatConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._ws: Any = None  # websockets connection (type varies by version)
        # echo_id → Future; used to await responses for specific actions
        self._pending: dict[str, asyncio.Future] = {}
        self._proxy = get_proxy(config.proxy)
        # Cache for user qid to avoid repeated API calls
        self._qid_cache: dict[str, str] = {}
        self._forward_pages: dict[str, _ForwardPage] = {}
        self._forward_file_url_cache: dict[str, str | None] = {}
        self._forward_gc_task: asyncio.Task | None = None
        self._forward_mount_registered = False
        self._event_tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self.bridge.register_sender(self.instance_id, self.send)
        self._ensure_forward_http_mount()
        self._ensure_forward_gc_task()

        ws_url = self.config.ws_url
        if self.config.ws_token:
            sep = "&" if "?" in ws_url else "?"
            ws_url = f"{ws_url}{sep}access_token={self.config.ws_token}"

        logger.info(f"NapCat [{self.instance_id}] connecting to {ws_url}")

        connect_kwargs: dict
        if self._proxy:
            logger.debug(f"NapCat [{self.instance_id}] using proxy {self._proxy}")
            connect_kwargs = {"proxy": self._proxy}
        else:
            connect_kwargs = {}

        while True:
            try:
                async with websockets.connect(ws_url, **connect_kwargs) as ws:
                    self._ws = ws
                    logger.info(f"NapCat [{self.instance_id}] connected")
                    await self._listen(ws)
            except websockets.exceptions.ConnectionClosedOK:
                logger.info(f"NapCat [{self.instance_id}] connection closed normally")
            except Exception as e:
                logger.error(f"NapCat [{self.instance_id}] connection error: {e}")
            finally:
                self._ws = None

            logger.info(f"NapCat [{self.instance_id}] reconnecting in 5s...")
            await asyncio.sleep(5)

    def _normalize_mount_path(self, path: str) -> str:
        normalized = (path or "/napcat-forward").strip()
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        if len(normalized) > 1 and normalized.endswith("/"):
            normalized = normalized[:-1]
        return normalized

    def _forward_mount_path(self) -> str:
        configured = self._normalize_mount_path(self.config.forward_render_mount_path)
        if configured == "/napcat-forward":
            return f"/napcat-forward/{self.instance_id}"
        return configured

    def _effective_forward_ttl(self) -> int:
        return max(60, int(self.config.forward_render_ttl_seconds or 0))

    def _build_forward_page_url(self, page_id: str, token: str) -> str:
        mount_path = self._forward_mount_path()
        base = (self.config.forward_assets_base_url or "").rstrip("/")

        if not base and self.http_server is not None:
            host = self.http_server.host or "127.0.0.1"
            if host == "0.0.0.0":
                host = "127.0.0.1"
            root_path = (self.http_server.root_path or "").rstrip("/")
            base = f"http://{host}:{self.http_server.port}{root_path}"

        if not base:
            base = "http://127.0.0.1:9080"

        return f"{base}{mount_path}/{page_id}?t={token}"

    def _ensure_forward_http_mount(self) -> None:
        if not self.config.forward_render_enabled:
            return
        if self.http_server is None:
            logger.warning(
                f"NapCat [{self.instance_id}] forward renderer not mounted: shared HTTP server unavailable"
            )
            return
        if self._forward_mount_registered:
            return

        app = FastAPI()

        @app.get("/{page_id}", response_class=HTMLResponse)
        async def _get_forward_page(
            page_id: str,
            t: str = Query(default="", min_length=1),
        ) -> HTMLResponse:
            page = self._forward_pages.get(page_id)
            if page is None and self.config.forward_render_persist_enabled:
                stored = msg_db().get_forward_page(page_id)
                if stored is not None and stored.get("token") == t:
                    page = _ForwardPage(
                        token=str(stored.get("token", "")),
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

            if page.token != t:
                raise HTTPException(status_code=404, detail="Forward page not found")

            if page.expires_at <= _utc_now() and page.destroyed_at is None:
                page.destroyed_at = _utc_now()
                if self.config.forward_render_persist_enabled:
                    msg_db().mark_forward_page_destroyed(
                        page_id, int(page.destroyed_at.timestamp())
                    )

            return HTMLResponse(content=page.html_content, status_code=200)

        mount_path = self._forward_mount_path()
        self.http_server.mount(
            instance_id=f"{self.instance_id}/forward",
            path=mount_path,
            app=app,
        )
        self._forward_mount_registered = True
        logger.info(
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
                logger.warning(f"NapCat [{self.instance_id}] invalid JSON received")
            except Exception as e:
                logger.error(f"NapCat [{self.instance_id}] handler error: {e}")

    def _spawn_event_task(self, data: dict) -> None:
        task = asyncio.create_task(self._handle(data))
        self._event_tasks.add(task)

        def _on_done(done_task: asyncio.Task) -> None:
            self._event_tasks.discard(done_task)
            if done_task.cancelled():
                return
            exc = done_task.exception()
            if exc is not None:
                logger.error(f"NapCat [{self.instance_id}] async handler error: {exc}")

        task.add_done_callback(_on_done)

    async def _handle(self, data: dict):
        # Action responses carry an "echo" field — ignore them
        if data.get("post_type") is None:
            return

        if data.get("post_type") != "message":
            return

        if data.get("message_type") == "group":
            await self._on_group_message(data)

    async def _on_group_message(self, event: dict):
        # NapCat echoes the bot's own sent messages back as real events;
        # self_id is the bot's QQ number, present on every OneBot 11 event.
        if event.get("user_id") == event.get("self_id"):
            return

        group_id = str(event.get("group_id", ""))
        user_id = str(event.get("user_id", ""))
        message_id = str(event.get("message_id", ""))
        message_seq = str(
            event.get("message_seq", event.get("real_id", event.get("seq", "")))
        )
        sender = event.get("sender", {})
        # Prefer group card (nickname-in-group) over global nickname
        nickname = sender.get("card") or sender.get("nickname") or user_id
        logger.debug(
            f"NapCat [{self.instance_id}] message from {nickname}({user_id}) "
            f"group={group_id} message_id={message_id} seq={message_seq}"
        )
        time = event.get("time")
        # Get user's qid
        qid = None  # await self._get_qid(user_id, group_id)

        face_as_emoji: bool = self.config.cqface_mode == "emoji"
        text, attachments, reply_id, mentions = await self._parse_message(
            event,
            face_as_emoji=face_as_emoji,
            source_group_id=group_id,
        )
        if not text.strip() and not attachments:
            logger.debug(
                f"NapCat [{self.instance_id}] ignoring empty message from {nickname}({user_id})"
            )
            return

        # QQ avatar endpoint (public, no auth)
        avatar_url = f"https://q.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640"

        msg = NormalizedMessage(
            platform="napcat",
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
            time=datetime.datetime.fromtimestamp(time).isoformat() if time else None,
            source_proxy=self._media_proxy,
            username=qid or user_id,
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
        reply_id: str | None = None
        mentions: list[dict] = []

        for seg in segments:
            t = seg.get("type", "")
            d = seg.get("data", {})

            match t:
                case "text":
                    text_parts.append(d.get("text", ""))

                case "at":
                    qq = str(d.get("qq", ""))
                    name = d.get("name")
                    if not name and qq != "all":
                        # Try to look up name in our DB
                        name = msg_db().get_user_name(self.instance_id, qq)
                    if not name:
                        name = qq

                    text_parts.append(f"@{name}")
                    if qq and qq != "all":
                        mentions.append({"id": qq, "name": name})

                case "image":
                    url = d.get("url") or d.get("file", "")
                    name = d.get("file", "image.jpg")
                    attachments.append(Attachment(type="image", url=url, name=name))

                case "record":  # voice message
                    url = d.get("url") or d.get("file", "")
                    name = d.get("file", "voice.amr")
                    attachments.append(Attachment(type="voice", url=url, name=name))

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
                    # Quote/reply — mention the replied-to message ID if available
                    reply_id = str(d.get("id", ""))

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

    def _token_short(self, length: int = 8) -> str:
        alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
        return "".join(secrets.choice(alphabet) for _ in range(length))

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

    def _render_forward_face_segment_html(self, seg_data: dict) -> str:
        face_id = str(seg_data.get("id", "")).strip()
        if not face_id:
            return html.escape("[表情]")

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
            return html.escape(f"[{kind_label}: {name}]")

        safe_url = html.escape(url)
        if kind_class == "voice":
            return (
                f"<div class='media-block media-voice'>"
                f"<span class='chip'>{html.escape(kind_label)}</span>"
                f"<audio class='media-player' controls preload='none' src='{safe_url}'></audio>"
                f"<a class='asset {html.escape(kind_class)}' href='{safe_url}' target='_blank' rel='noopener noreferrer'>"
                f"{name}</a>"
                f"</div>"
            )
        if kind_class == "video":
            return (
                f"<div class='media-block media-video'>"
                f"<span class='chip'>{html.escape(kind_label)}</span>"
                f"<video class='media-player' controls preload='metadata' src='{safe_url}'></video>"
                f"<a class='asset {html.escape(kind_class)}' href='{safe_url}' target='_blank' rel='noopener noreferrer'>"
                f"{name}</a>"
                f"</div>"
            )
        return (
            f"<span class='chip'>{html.escape(kind_label)}</span>"
            f"<a class='asset {html.escape(kind_class)}' href='{safe_url}' "
            "target='_blank' rel='noopener noreferrer'>"
            f"{name}</a>"
        )

    async def _render_forward_voice_asset_html(self, seg_data: dict) -> str:
        name = html.escape(self._segment_name(seg_data, "voice.amr"))
        url = self._segment_url(seg_data)
        if not url:
            return html.escape(f"[语音: {name}]")

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
                f"<div class='media-block media-voice'>"
                f"<span class='chip'>语音</span>"
                f"<a class='asset voice' href='{safe_url}' target='_blank' rel='noopener noreferrer'>"
                f"{name}</a>"
                f"</div>"
            )

        data, mime = result
        data_url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        safe_data_url = html.escape(data_url)
        safe_url = html.escape(url)
        return (
            f"<div class='media-block media-voice'>"
            f"<span class='chip'>语音</span>"
            f"<audio class='media-player' controls preload='none' src='{safe_data_url}'></audio>"
            f"<a class='asset voice' href='{safe_url}' target='_blank' rel='noopener noreferrer'>"
            f"{name}</a>"
            f"</div>"
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
            return "未知"
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
    ) -> str:
        if not file_id:
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
            action_candidates.append(
                (
                    "get_group_file_url",
                    {"group_id": source_group_id, "file_id": file_id},
                )
            )
        action_candidates.append(("get_file", {"file_id": file_id}))

        for action, params in action_candidates:
            response = await self._call(action, params, timeout=12.0)
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

        logger.debug(
            f"NapCat [{self.instance_id}] forward file download url unresolved for file_id={file_id}"
        )
        self._forward_file_url_cache[cache_key] = None
        return ""

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
        size_text = html.escape(self._format_size_human(size_bytes))
        file_id_text = html.escape(file_id or "未知")

        url = self._segment_url(seg_data)
        if not url and file_id:
            url = await self._resolve_forward_file_download_url(
                file_id=file_id,
                source_group_id=source_group_id,
            )

        download_html = "<span class='asset file disabled'>暂无法下载</span>"
        if url:
            safe_url = html.escape(url)
            download_html = (
                f"<a class='asset file' href='{safe_url}' "
                "target='_blank' rel='noopener noreferrer'>"
                f"下载 {name}</a>"
            )

        return (
            "<div class='file-block'>"
            "<span class='chip'>文件</span>"
            f"<div class='file-name'>{name}</div>"
            f"<div class='file-meta'>大小: {size_text} · file_id: {file_id_text}</div>"
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
        match = _RICHHEADER_RE.search(text)
        if not match:
            return text, None

        attrs = dict(_RICHHEADER_ATTR_RE.findall(match.group(1)))
        clean = (text[: match.start()] + text[match.end() :]).strip()
        return clean, attrs or None

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
            "platform": "napcat",
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
            logger.debug(
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

    async def _render_forward_nodes_html(
        self,
        nodes: list[dict],
        *,
        source_group_id: str,
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
            richheader: dict | None = None
            reply_to_id = ""
            user_id_reliable = user_id not in unreliable_user_ids

            if not user_id_reliable and user_id:
                logger.debug(
                    f"NapCat [{self.instance_id}] forward node user_id marked unreliable: {user_id}"
                )

            logger.debug(
                f"NapCat [{self.instance_id}] forward node sender resolved "
                f"nickname={nickname!r} user_id={user_id!r} "
                f"raw_sender={node.get('sender')!r}"
            )

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
                    image_url = self._segment_url(seg_data)
                    if image_url:
                        content_parts.append(
                            f"<img class='fwd-image' src='{html.escape(image_url)}' "
                            "loading='lazy' referrerpolicy='no-referrer' alt='图片'/>"
                        )
                    else:
                        content_parts.append(html.escape("[图片]"))
                elif seg_type == "record":
                    content_parts.append(
                        await self._render_forward_voice_asset_html(seg_data)
                    )
                elif seg_type == "video":
                    content_parts.append(
                        self._render_forward_asset_html(
                            seg_data,
                            kind_label="视频",
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
                                depth=depth + 1,
                            )
                        )
                    else:
                        plain_text_parts.append("[合并转发]")
                        content_parts.append(html.escape("[合并转发]"))
                elif seg_type == "reply":
                    reply_to_id = self._forward_reply_target_id(seg_data)
                elif seg_type == "face":
                    content_parts.append(
                        self._render_forward_face_segment_html(seg_data)
                    )
                elif seg_type == "mface":
                    image_url = self._segment_url(seg_data)
                    if image_url:
                        content_parts.append(
                            f"<img class='fwd-image' src='{html.escape(image_url)}' "
                            "loading='lazy' referrerpolicy='no-referrer' alt='表情'/>"
                        )
                    else:
                        summary = str(seg_data.get("summary", "")).strip()
                        if summary:
                            plain_text_parts.append(summary)
                            content_parts.append(html.escape(summary))
                        else:
                            plain_text_parts.append("[表情]")
                            content_parts.append(html.escape("[表情]"))

            if richheader is None:
                msg_text = "".join(plain_text_parts).strip()
                richheader = self._apply_forward_msg_format_header(
                    msg_format=msg_format,
                    nickname=nickname,
                    user_id=user_id if user_id_reliable else "",
                    msg_text=msg_text,
                )

            message_html = "".join(content_parts).strip() or html.escape("[空消息]")
            message_text = "".join(plain_text_parts).strip() or "[空消息]"
            default_sender = f"{nickname}" + (
                f" ({user_id})" if user_id and user_id_reliable else ""
            )
            header_title = html.escape(
                str(richheader.get("title", "")).strip() if richheader else ""
            ) or html.escape(default_sender)
            header_content = html.escape(
                str(richheader.get("content", "")).strip() if richheader else ""
            )

            avatar_url = ""
            if richheader:
                avatar_url = str(richheader.get("avatar", "")).strip()
            if not avatar_url and user_id and user_id_reliable:
                avatar_url = f"https://q.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=160"

            avatar_html = ""
            if avatar_url.startswith(("http://", "https://")):
                avatar_html = (
                    f"<img class='avatar' src='{html.escape(avatar_url)}' "
                    "alt='avatar' referrerpolicy='no-referrer' loading='lazy'/>"
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
                "header_title": header_title,
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
                    "<div class='reply-preview-title'>回复消息</div>"
                    "</blockquote>"
                )

            rendered.append(
                "<article class='msg'>"
                "<div class='sender'>"
                f"{item.get('avatar_html', '')}"
                "<div class='sender-meta'>"
                f"<div class='sender-main'>{item.get('header_title', '')}</div>"
                f"{item.get('header_content_html', '')}"
                "</div>"
                "</div>"
                f"{reply_html}"
                f"<div class='content'>{item.get('message_html', '')}</div>"
                "</article>"
            )

        return "\n".join(rendered)

    async def _render_forward_nested_html(
        self,
        nodes: list[dict],
        *,
        source_group_id: str,
        depth: int,
    ) -> str:
        nested_body = await self._render_forward_nodes_html(
            nodes,
            source_group_id=source_group_id,
            depth=depth,
        )
        return (
            "<details class='nested-forward'>"
            "<summary class='nested-forward-title'>嵌套合并转发（点击展开）</summary>"
            f"<div class='nested-forward-body'>{nested_body}</div>"
            "</details>"
        )

    def _render_forward_page_html(
        self,
        title: str,
        body_html: str,
        meta_primary_text: str,
        meta_secondary_text: str,
        *,
        created_at: datetime.datetime,
        expires_at: datetime.datetime,
        destroyed_at: datetime.datetime | None = None,
    ) -> str:
        title_html = html.escape(title)
        meta_primary_html = html.escape(meta_primary_text)
        meta_secondary_html = html.escape(meta_secondary_text)
        page_state = "destroyed" if destroyed_at is not None else "active"
        page_state_text = "已销毁" if destroyed_at is not None else "有效"
        page_state_banner = "已销毁" if destroyed_at is not None else "当前页面有效"
        page_state_detail = (
            "当前页面已超过有效期"
            if destroyed_at is not None
            else "页面将在到期后自动切换为已销毁"
        )
        return _get_forward_page_template().substitute(
            title=title_html,
            meta_primary=meta_primary_html,
            meta_secondary=meta_secondary_html,
            created_at_epoch=str(int(created_at.timestamp())),
            expires_at_epoch=str(int(expires_at.timestamp())),
            destroyed_at_epoch=str(int(destroyed_at.timestamp()))
            if destroyed_at
            else "",
            page_state=page_state,
            page_state_text=page_state_text,
            page_state_banner=page_state_banner,
            page_state_detail=page_state_detail,
            body=body_html,
        )

    async def _render_forward_segment(
        self,
        seg_data: dict,
        *,
        source_group_id: str,
    ) -> str:
        if not self.config.forward_render_enabled:
            return "[Forwarded messages]"

        forward_id = str(seg_data.get("id", "")).strip()
        if not forward_id:
            return "[Forwarded messages]"

        logger.debug(
            f"NapCat [{self.instance_id}] rendering forward segment id={forward_id}"
        )

        response = await self._call("get_forward_msg", {"id": forward_id}, timeout=30.0)
        if not response or response.get("status") != "ok":
            logger.warning(
                f"NapCat [{self.instance_id}] get_forward_msg failed for id={forward_id}: {response}"
            )
            return "[Forwarded messages]"

        payload = response.get("data") or {}
        nodes = payload.get("messages")
        if nodes is None:
            nodes = payload.get("message")
        if not isinstance(nodes, list):
            logger.warning(
                f"NapCat [{self.instance_id}] get_forward_msg no messages for id={forward_id}"
            )
            return "[Forwarded messages]"

        body_html = await self._render_forward_nodes_html(
            nodes,
            source_group_id=source_group_id,
        )
        created_at = _utc_now()
        created_at_ts = int(created_at.timestamp())
        ttl = self._effective_forward_ttl()
        expires_at = created_at + datetime.timedelta(seconds=ttl)
        expires_at_ts = int(expires_at.timestamp())
        meta_primary_text = (
            f"生成于 {created_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %z')}"
        )
        meta_secondary_text = (
            f"有效期至 {expires_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %z')} · "
            f"距离销毁约 {self._format_duration_cn(ttl)}"
        )
        page_html = self._render_forward_page_html(
            title="QQ 合并转发消息",
            body_html=body_html,
            meta_primary_text=meta_primary_text,
            meta_secondary_text=meta_secondary_text,
            created_at=created_at,
            expires_at=expires_at,
        )

        page_id = uuid.uuid4().hex
        token = self._token_short()
        self._forward_pages[page_id] = _ForwardPage(
            token=token,
            html_content=page_html,
            created_at=created_at,
            expires_at=expires_at,
        )
        if self.config.forward_render_persist_enabled:
            msg_db().save_forward_page(
                page_id=page_id,
                instance_id=self.instance_id,
                token=token,
                html_content=page_html,
                created_at=created_at_ts,
                expires_at=expires_at_ts,
            )

        link = self._build_forward_page_url(page_id, token)
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
        self, action: str, params: dict, timeout: float = 30.0
    ) -> dict | None:
        """Send a OneBot action and await its echo response."""
        if self._ws is None:
            return None
        echo = str(uuid.uuid4())
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[echo] = fut
        payload = {"action": action, "params": params, "echo": echo}
        try:
            await self._ws.send(json.dumps(payload, ensure_ascii=False))
            return await asyncio.wait_for(fut, timeout=timeout)
        except TimeoutError:
            logger.warning(f"NapCat [{self.instance_id}] action '{action}' timed out")
            self._pending.pop(echo, None)
            return None
        except Exception as e:
            logger.error(f"NapCat [{self.instance_id}] action '{action}' error: {e}")
            self._pending.pop(echo, None)
            return None

    # async def _get_qid(self, user_id: str, group_id: str | None = None) -> str:
    #     """Get user's qid using NapCat API with caching."""
    #     # Check cache first
    #     if user_id in self._qid_cache:
    #         return self._qid_cache[user_id]

    #     try:
    #         # Use get_stranger_info to get qid
    #         result = await self._call(
    #             "get_stranger_info", {"user_id": user_id}, timeout=30.0
    #         )
    #         logger.debug(
    #             f"NapCat [{self.instance_id}] get_stranger_info result for {user_id}: {result}"
    #         )
    #         if result and result.get("status") == "ok" and result.get("data"):
    #             data = result["data"]
    #             qid = data.get("qid", "")
    #             # Cache the result
    #             if qid:
    #                 self._qid_cache[user_id] = qid
    #             logger.debug(f"NapCat [{self.instance_id}] qid for {user_id}: {qid}")
    #             return qid
    #         else:
    #             logger.warning(
    #                 f"NapCat [{self.instance_id}] get_stranger_info failed for {user_id}: {result}"
    #             )
    #     except Exception as e:
    #         logger.warning(
    #             f"NapCat [{self.instance_id}] failed to get qid for {user_id}: {e}"
    #         )
    #     return ""

    async def _upload_file_stream(self, data_bytes: bytes, filename: str) -> str | None:
        """
        Upload bytes via OneBot upload_file_stream (chunked base64).

        NapCat processes chunk_data and is_complete in separate branches:
        when chunk_data is present it stores the chunk and returns early,
        so is_complete must be sent as a separate final request with no chunk_data.

        Returns the server-side file_path on success, or None on failure.
        """
        CHUNK_SIZE = 256 * 1024  # 256 KB per chunk
        total = len(data_bytes)
        total_chunks = max(1, math.ceil(total / CHUNK_SIZE))
        stream_id = str(uuid.uuid4())

        # Upload all chunks (NapCat param is "filename", not "file_name")
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
                logger.warning(
                    f"NapCat [{self.instance_id}] stream upload chunk {i}/{total_chunks} "
                    f"got no response for '{filename}'"
                )
                return None
            if resp.get("status") == "failed":
                logger.warning(
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
            logger.warning(
                f"NapCat [{self.instance_id}] stream upload completion failed "
                f"for '{filename}': {resp}"
            )
            return None

        data = resp.get("data") or {}
        file_path = data.get("file_path")
        if not file_path:
            logger.warning(
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
        if not group_id:
            logger.warning(
                f"NapCat [{self.instance_id}] send: no group_id in channel {channel}"
            )
            return None

        if self._ws is None:
            logger.warning(
                f"NapCat [{self.instance_id}] send: not connected, message dropped"
            )
            return None

        segments: list[dict] = []

        reply_to_id = kwargs.get("reply_to_id")
        if reply_to_id:
            segments.append({"type": "reply", "data": {"id": str(reply_to_id)}})

        rich_header = kwargs.get("rich_header")
        if rich_header:
            t, c = rich_header.get("title", ""), rich_header.get("content", "")
            prefix = f"[{t}" + (f" · {c}" if c else "") + "]"
            text = f"{prefix}\n{text}" if text else prefix

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
                    # Add mention segment
                    segments.append({"type": "at", "data": {"qq": m["id"]}})
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
                        mode = self._resolve_send_mode(len(data_bytes))
                        if mode == "base64":
                            b64 = base64.b64encode(data_bytes).decode()
                            await self._call(
                                "upload_group_file",
                                {
                                    "group_id": int(group_id),
                                    "file": f"base64://{b64}",
                                    "name": fname,
                                },
                            )
                        else:  # stream (default)
                            file_path = await self._upload_file_stream(
                                data_bytes, fname
                            )
                            if file_path:
                                await self._call(
                                    "upload_group_file",
                                    {
                                        "group_id": int(group_id),
                                        "file": file_path,
                                        "name": fname,
                                    },
                                )
                            else:
                                segments.append(
                                    {
                                        "type": "text",
                                        "data": {"text": f"\n[文件: {att.name}]"},
                                    }
                                )
                    else:
                        segments.append(
                            {
                                "type": "text",
                                "data": {"text": f"\n[文件: {att.name}]"},
                            }
                        )

        if not segments:
            return None

        resp = await self._call(
            "send_group_msg",
            {
                "group_id": int(group_id),
                "message": segments,
            },
        )
        if resp and resp.get("status") == "ok":
            data = resp.get("data") or {}
            return str(data.get("message_id", ""))
        return None


register("napcat", NapCatConfig, NapCatDriver)
