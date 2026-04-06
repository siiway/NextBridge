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
import secrets
import uuid
from dataclasses import dataclass
from pathlib import Path
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
    forward_render_enabled: bool = True
    forward_render_ttl_seconds: int = 86400
    forward_render_mount_path: str = "/napcat-forward"
    forward_assets_base_url: str = ""
    # Merged-forward face rendering strategy:
    # - false: render by cqface mapping (unicode)
    # - true/unset: render by default gif host
    # - string: use custom gif host base URL
    forward_render_cqface_gif: bool | str = True
    proxy: str | None = UNSET


logger = log.get_logger()

_DEFAULT_FORWARD_CQFACE_GIF_HOST: str = "https://nextbridge.siiway.org/db/cqface-gif/"


@dataclass(slots=True)
class _ForwardPage:
    token: str
    html_content: str
    expires_at: datetime.datetime


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
        self._forward_gc_task: asyncio.Task | None = None
        self._forward_mount_registered = False

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
            if page is None:
                raise HTTPException(status_code=404, detail="Forward page not found")

            if page.expires_at <= _utc_now():
                self._forward_pages.pop(page_id, None)
                raise HTTPException(status_code=410, detail="Forward page expired")

            if page.token != t:
                raise HTTPException(status_code=404, detail="Forward page not found")

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
                await self._handle(data)
            except json.JSONDecodeError:
                logger.warning(f"NapCat [{self.instance_id}] invalid JSON received")
            except Exception as e:
                logger.error(f"NapCat [{self.instance_id}] handler error: {e}")

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
        sender = event.get("sender", {})
        # Prefer group card (nickname-in-group) over global nickname
        nickname = sender.get("card") or sender.get("nickname") or user_id
        time = event.get("time")
        # Get user's qid
        qid = None  # await self._get_qid(user_id, group_id)

        face_as_emoji: bool = self.config.cqface_mode == "emoji"
        text, attachments, reply_id, mentions = await self._parse_message(
            event, face_as_emoji=face_as_emoji
        )
        if not text.strip() and not attachments:
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
        self, event: dict, *, face_as_emoji: bool = False
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
                    forward_text = await self._render_forward_segment(d)
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

    def _render_forward_nodes_html(self, nodes: list[dict]) -> str:
        rendered: list[str] = []

        for node in nodes:
            sender = node.get("sender") or {}
            nickname = sender.get("nickname") or sender.get("card") or "Unknown"
            user_id = str(sender.get("user_id", ""))
            content = node.get("content")
            if content is None:
                content = node.get("message")
            if content is None and isinstance(node.get("data"), dict):
                content = node["data"].get("content") or node["data"].get("message")

            content_parts: list[str] = []
            for seg in content if isinstance(content, list) else []:
                seg_type = seg.get("type", "")
                seg_data = seg.get("data") or {}

                if seg_type == "text":
                    content_parts.append(html.escape(str(seg_data.get("text", ""))))
                elif seg_type == "at":
                    qq = str(seg_data.get("qq", ""))
                    name = seg_data.get("name") or qq
                    content_parts.append(html.escape(f"@{name}"))
                elif seg_type == "image":
                    content_parts.append(html.escape("[图片]"))
                elif seg_type == "record":
                    content_parts.append(html.escape("[语音]"))
                elif seg_type == "video":
                    content_parts.append(html.escape("[视频]"))
                elif seg_type == "file":
                    content_parts.append(html.escape("[文件]"))
                elif seg_type == "forward":
                    content_parts.append(html.escape("[合并转发]"))
                elif seg_type == "face":
                    content_parts.append(
                        self._render_forward_face_segment_html(seg_data)
                    )

            message_html = "".join(content_parts).strip() or html.escape("[空消息]")
            sender_display = html.escape(
                f"{nickname}" + (f" ({user_id})" if user_id else "")
            )
            rendered.append(
                "<article class='msg'>"
                f"<div class='sender'>{sender_display}</div>"
                f"<div class='content'>{message_html}</div>"
                "</article>"
            )

        return "\n".join(rendered)

    def _render_forward_page_html(
        self, title: str, body_html: str, expire_text: str
    ) -> str:
        title_html = html.escape(title)
        expire_html = html.escape(expire_text)
        return (
            "<!doctype html>"
            "<html lang='zh-CN'><head><meta charset='utf-8'/>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
            f"<title>{title_html}</title>"
            "<style>"
            ":root{--bg:#f7f6f3;--ink:#1f2629;--soft:#647177;--line:#dcd8cf;--card:#fffdf8;}"
            "*{box-sizing:border-box}"
            "body{margin:0;padding:24px;font-family:'Noto Sans CJK SC','PingFang SC','Microsoft YaHei',sans-serif;background:linear-gradient(180deg,#f7f6f3,#f0ede5);color:var(--ink)}"
            ".wrap{max-width:860px;margin:0 auto}"
            "h1{margin:0 0 10px;font-size:24px;line-height:1.2}"
            ".meta{margin-bottom:18px;color:var(--soft);font-size:13px}"
            ".msg{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px;margin:10px 0;box-shadow:0 1px 0 rgba(0,0,0,.02)}"
            ".sender{font-weight:700;font-size:13px;margin-bottom:8px;color:#2f3d42}"
            ".content{margin:0;white-space:pre-wrap;word-break:break-word;font-family:inherit;font-size:14px;line-height:1.6}"
            ".cqface{height:1.3em;width:1.3em;vertical-align:-0.22em;object-fit:contain}"
            "</style></head><body><main class='wrap'>"
            f"<h1>{title_html}</h1>"
            f"<div class='meta'>{expire_html}</div>"
            f"{body_html}"
            "</main></body></html>"
        )

    async def _render_forward_segment(self, seg_data: dict) -> str:
        if not self.config.forward_render_enabled:
            return "[Forwarded messages]"

        forward_id = str(seg_data.get("id", "")).strip()
        if not forward_id:
            return "[Forwarded messages]"

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

        body_html = self._render_forward_nodes_html(nodes)
        ttl = self._effective_forward_ttl()
        expires_at = _utc_now() + datetime.timedelta(seconds=ttl)
        expire_text = (
            f"有效期至 {expires_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %z')}"
        )
        page_html = self._render_forward_page_html(
            title="QQ 合并转发消息",
            body_html=body_html,
            expire_text=expire_text,
        )

        page_id = uuid.uuid4().hex
        token = self._token_short()
        self._forward_pages[page_id] = _ForwardPage(
            token=token,
            html_content=page_html,
            expires_at=expires_at,
        )

        link = self._build_forward_page_url(page_id, token)
        return f"[QQ Combined Forward] {link}"

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
