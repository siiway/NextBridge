# Workbench control-plane driver.
#
# Unlike chat platform drivers, this one doesn't send/receive chat messages
# — it maintains an outbound WebSocket to a Workbench instance and exposes a
# read-only RPC surface (drivers, rules, recent messages, user bindings).
# NapCat-style reverse-WS: NextBridge dials Workbench, never the other way.
#
# Config keys (under workbench.<instance_id>):
#   url                       — Workbench base URL, e.g. https://dash.siiway.org
#   token                     — bearer token issued by Workbench at pairing
#   workbench_instance_id     — stable id assigned by Workbench at pairing time
#                               (the per-driver instance_id is just a local label)
#   instance_name             — optional human label shown in the Workbench UI
#   reconnect_min_seconds     — initial reconnect backoff (default 2)
#   reconnect_max_seconds     — max reconnect backoff (default 60)
#   heartbeat_seconds         — heartbeat interval (default 30)
#
# Pairing flow (see `python main.py workbench pair`):
#   1. User clicks "Pair NextBridge" in Workbench, gets a one-time code.
#   2. `python main.py workbench pair <url> <code>` exchanges the code for a
#      long-lived token and writes a `workbench.default` block into the
#      local config file.
#   3. Restart NextBridge; this driver loads, dials Workbench, and stays
#      online until cancelled.

from __future__ import annotations

import asyncio
import inspect
import json
import random
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse, urlunparse

import httpx
import websockets
from pydantic import field_validator
from websockets.asyncio.client import ClientConnection

import services.config_io as config_io
import services.logger as log
import services.util as u
from drivers import BaseDriver
from drivers.registry import register
from services.config_schema import _DriverConfig
from services.db import msg_db
from services.message import Attachment, NormalizedMessage

if TYPE_CHECKING:
    pass

logger = log.get_logger()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class WorkbenchConfig(_DriverConfig):
    """Per-instance config for the Workbench reverse-WS client."""

    url: str = ""
    """Workbench base URL, e.g. ``https://dash.siiway.org``.
    The client connects to ``{url}/api/nextbridge/relay`` over WSS."""

    token: str = ""
    """Bearer token issued by Workbench at pairing time."""

    workbench_instance_id: str = ""
    """Stable identifier assigned by Workbench at pairing time. Sent up in
    the hello frame so the Workbench UI can match this connection to the
    instance record stored on its side."""

    instance_name: str = ""
    """Human-readable label shown in Workbench UI. Optional."""

    reconnect_min_seconds: int = 2
    """Initial reconnect backoff (seconds)."""

    reconnect_max_seconds: int = 60
    """Max reconnect backoff (seconds)."""

    heartbeat_seconds: int = 30
    """Heartbeat interval; the client sends a ping every N seconds."""

    @field_validator("url", mode="before")
    def normalize_url(cls, v):
        if v is None:
            return ""
        if not isinstance(v, str):
            raise ValueError(f"Invalid workbench.url: {v}")
        u_ = v.strip()
        if not u_:
            return ""
        if not u_.startswith(("http://", "https://")):
            u_ = f"https://{u_.lstrip('/')}"
        return u_.rstrip("/")


# ---------------------------------------------------------------------------
# RPC method registry — handlers exposed to Workbench
#
# Handlers receive the driver instance so they can reach both the bridge
# (driver.bridge) and the WS event queue (driver._buffer_event) — the latter
# is needed for the bidirectional chat methods that echo self-authored
# messages back to the Workbench UI without going through the bridge's
# echo-suppression path.
# ---------------------------------------------------------------------------

Handler = Callable[["WorkbenchDriver", dict[str, Any]], "Awaitable[Any] | Any"]

_RPC_METHODS: dict[str, Handler] = {}


def _rpc(name: str):
    def deco(fn: Handler) -> Handler:
        _RPC_METHODS[name] = fn
        return fn

    return deco


@_rpc("meta.info")
def _meta_info(driver: "WorkbenchDriver", _params: dict) -> dict:
    return {
        "command_prefix": driver.bridge.command_prefix,
        "strict_echo_match": driver.bridge.strict_echo_match,
        "sender_count": len(driver.bridge.senders_snapshot()),
        "rule_count": len(driver.bridge.rules_snapshot()),
    }


@_rpc("drivers.list")
def _drivers_list(driver: "WorkbenchDriver", _params: dict) -> dict:
    """Snapshot of registered driver instances.

    Connection state is implicit: a sender registration means the driver
    successfully reached its platform's connect/handshake step.
    """
    return {"drivers": driver.bridge.senders_snapshot()}


@_rpc("rules.list")
def _rules_list(driver: "WorkbenchDriver", _params: dict) -> dict:
    return {"rules": driver.bridge.rules_snapshot()}


@_rpc("rules.reload")
def _rules_reload(driver: "WorkbenchDriver", _params: dict) -> dict:
    """Re-read the rules file from disk.

    TODO(workbench-rules-crud): replace this stub with proper rules.add /
    rules.update / rules.delete RPC methods once Workbench's /bridge/config
    UI is ready to drive them. Until then, users edit rules.{yaml,json,toml}
    on the NextBridge host directly and call this to pick up changes.
    """
    before = len(driver.bridge.rules_snapshot())
    driver.bridge.load_rules()
    after = len(driver.bridge.rules_snapshot())
    return {"before": before, "after": after}


@_rpc("messages.recent")
def _messages_recent(_driver: "WorkbenchDriver", params: dict) -> dict:
    limit = int(params.get("limit", 50))
    return {"mappings": msg_db().recent_mappings(limit=limit)}


@_rpc("bindings.list")
def _bindings_list(_driver: "WorkbenchDriver", params: dict) -> dict:
    limit = int(params.get("limit", 200))
    return {"bindings": msg_db().list_user_bindings(limit=limit)}


@_rpc("db.stats")
def _db_stats(_driver: "WorkbenchDriver", _params: dict) -> dict:
    return msg_db().stats()


# ---------------------------------------------------------------------------
# Chat RPC — bidirectional messaging between Workbench and the bridge
# ---------------------------------------------------------------------------


_NON_ADDRESS_KEYS = {
    "msg",
    "msg_format",
    "webhook_msg_format",
    "bot_msg_format",
    "webhook_url",
}


def _normalize_channel_addr(ch: dict) -> dict:
    """Strip format/webhook keys that aren't part of the channel address."""
    return {k: v for k, v in ch.items() if k not in _NON_ADDRESS_KEYS}


def _serialise_attachments(raw) -> list[dict]:  # type: ignore[no-untyped-def]
    """Project the bridge's ``Attachment`` dataclasses into JSON-friendly dicts.

    Drops the ``data`` bytes field — those don't survive JSON serialisation
    and Workbench only needs a URL to render the image / link.
    """
    if not raw:
        return []
    out: list[dict] = []
    for att in raw:
        if isinstance(att, Attachment):
            out.append(
                {
                    "type": att.type,
                    "url": att.url,
                    "name": att.name,
                    "size": att.size,
                }
            )
        elif isinstance(att, dict):
            # Some drivers may pass plain dicts; normalise to the same shape.
            out.append(
                {
                    "type": str(att.get("type", "")),
                    "url": str(att.get("url", "")),
                    "name": str(att.get("name", "")),
                    "size": int(att.get("size", -1) or -1),
                }
            )
    return out


@_rpc("chat.channels")
def _chat_channels(driver: "WorkbenchDriver", _params: dict) -> dict:
    """List addressable Workbench channels derived from the rules file.

    A "channel" here corresponds to one rule that includes this Workbench
    instance — i.e. an interconnection group. The response carries the
    Workbench-side address plus the peer instances participating in the
    same group so the frontend can render the full group composition.
    """
    inst = driver.instance_id
    senders = {
        s["instance_id"]: s.get("platform") or ""
        for s in driver.bridge.senders_snapshot()
    }
    seen_keys: set[str] = set()
    out: list[dict] = []
    for rule in driver.bridge.rules_snapshot():
        for slot in ("to", "channels"):
            block = rule.get(slot)
            if not isinstance(block, dict):
                continue
            ch = block.get(inst)
            if not isinstance(ch, dict):
                continue

            addr = _normalize_channel_addr(ch)
            # Group identity is the (rule_id, workbench address) tuple so a
            # single rule that lists Workbench in both `to` and `channels`
            # (degenerate but possible) doesn't show up twice.
            rule_id = str(rule.get("id", ""))
            key = rule_id + "|" + json.dumps(
                addr, sort_keys=True, ensure_ascii=True, default=str
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)

            peers: list[dict] = []
            for peer_inst, peer_ch in block.items():
                if peer_inst == inst:
                    continue
                if not isinstance(peer_ch, dict):
                    continue
                peers.append(
                    {
                        "instance_id": peer_inst,
                        "platform": senders.get(peer_inst, ""),
                        "address": _normalize_channel_addr(peer_ch),
                    }
                )

            out.append(
                {
                    "rule_id": rule_id,
                    "rule_type": str(rule.get("type", "forward")),
                    "address": addr,
                    "peers": peers,
                }
            )
    return {"channels": out}


@_rpc("chat.send")
async def _chat_send(driver: "WorkbenchDriver", params: dict) -> dict:
    """Send a message from Workbench into the bridge.

    The message is dispatched through ``bridge.on_message`` so it fans out
    to every rule that has this Workbench instance on its source side.
    The bridge's echo suppression keeps the message from coming back via
    ``send()`` on the same driver, so we also fire a local ``chat.inbound``
    event so the Workbench UI sees its own message in the channel log.
    """
    channel = params.get("channel") or {}
    text = (params.get("text") or "").strip()
    user = (params.get("user") or "").strip() or "workbench-user"
    user_id = (params.get("user_id") or "").strip()
    user_avatar = (params.get("user_avatar") or "").strip()

    if not text:
        raise ValueError("text is required")
    if not isinstance(channel, dict):
        raise ValueError("channel must be an object")

    addr = _normalize_channel_addr(channel)
    message_id = f"wb-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    # Echo to UI first so the user sees their message immediately.
    driver._buffer_event(
        "chat.inbound",
        {
            "channel": addr,
            "platform": "workbench",
            "instance_id": driver.instance_id,
            "user": user,
            "user_id": user_id,
            "user_avatar": user_avatar,
            "text": text,
            "message_id": message_id,
            "time": now,
            "self": True,
        },
    )

    msg = NormalizedMessage(
        platform="workbench",
        instance_id=driver.instance_id,
        channel=addr,
        nickname=user,
        username=user,
        user_id=user_id,
        user_avatar=user_avatar,
        text=text,
        message_id=message_id,
        time=now,
    )

    try:
        await driver.bridge.on_message(msg)
    except Exception as exc:
        logger.opt(exception=exc).warning(
            f"Workbench [{driver.instance_id}] chat.send dispatch failed"
        )
        raise

    return {"ok": True, "message_id": message_id, "time": now}


# ---------------------------------------------------------------------------
# Driver implementation
# ---------------------------------------------------------------------------


def _to_wss_url(base: str) -> str:
    """``https://host`` → ``wss://host/api/nextbridge/relay``."""
    parsed = urlparse(base)
    scheme = parsed.scheme.lower()
    if scheme == "https":
        ws_scheme = "wss"
    elif scheme == "http":
        ws_scheme = "ws"
    else:
        ws_scheme = scheme or "wss"
    path = parsed.path.rstrip("/") + "/api/nextbridge/relay"
    return urlunparse((ws_scheme, parsed.netloc, path, "", "", ""))


class WorkbenchDriver(BaseDriver[WorkbenchConfig]):
    """Maintains an outbound WSS link to a Workbench instance.

    Acts as both a control plane (RPC for status/rules/etc) and a chat
    endpoint — when a rule routes a message to this Workbench instance,
    ``send`` fires a ``chat.inbound`` event so the Workbench UI can render
    it. Messages typed in the Workbench UI come back as ``chat.send`` RPCs
    that go through ``bridge.on_message`` for normal fan-out.
    """

    def __init__(self, instance_id: str, config: WorkbenchConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._ws: ClientConnection | None = None
        self._send_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._event_buffer: asyncio.Queue[dict] = asyncio.Queue(maxsize=512)
        self._version: str = "UNKNOWN"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        if not self.config.url or not self.config.token:
            logger.warning(
                f"Workbench [{self.instance_id}]: url/token missing; not starting. "
                f"Run `python main.py workbench pair <url> <code>` to configure."
            )
            return

        # Best-effort version read for the hello frame.
        try:
            import tomllib

            with open("pyproject.toml", "rb") as f:
                self._version = str(
                    tomllib.load(f).get("project", {}).get("version", "")
                ).strip() or "UNKNOWN"
        except Exception:
            pass

        # Observe bridge events so they flow up to Workbench.
        self.bridge.register_observer(self._on_bridge_event)

        # Participate in message routing so bridge can fan out to us.
        self.bridge.register_sender(self.instance_id, self.send)

        backoff = max(1, int(self.config.reconnect_min_seconds))
        max_backoff = max(backoff, int(self.config.reconnect_max_seconds))

        url = _to_wss_url(self.config.url)
        logger.info(f"Workbench [{self.instance_id}] target: {url}")

        try:
            while not self._stop.is_set():
                try:
                    await self._session(url)
                    backoff = max(1, int(self.config.reconnect_min_seconds))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        f"Workbench [{self.instance_id}] disconnected "
                        f"({type(exc).__name__}): {exc}; retrying in {backoff}s"
                    )
                jitter = random.uniform(0, 0.3 * backoff)
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=backoff + jitter
                    )
                    break
                except asyncio.TimeoutError:
                    pass
                backoff = min(max_backoff, backoff * 2)
        finally:
            logger.info(f"Workbench [{self.instance_id}] stopped")

    async def send(self, channel: dict, text: str, **kwargs) -> str | None:
        """Called by the bridge when a rule routes a message to this Workbench.

        Translates the dispatch into a ``chat.inbound`` event so the
        connected Workbench frontend can render the message. Returns a
        synthetic message id; the bridge uses it for reply-mapping
        purposes (which Workbench currently doesn't make use of, but
        the contract requires returning *something* on success).
        """
        message_id = f"wb-{uuid.uuid4().hex[:12]}"

        # Pull the originator context out of the kwargs the bridge passes
        # along (see Bridge._build_formatted in services/bridge.py).
        platform = str(kwargs.get("platform", "") or "")
        user_id = str(kwargs.get("user_id", "") or "")
        user_avatar = str(kwargs.get("user_avatar", "") or "")

        # QQ doesn't always populate user_avatar on inbound messages, but the
        # public avatar endpoint can be derived from the numeric uin. Fall
        # back to it so the chat UI has something to show.
        if not user_avatar and platform == "qq" and user_id.isdigit():
            user_avatar = (
                f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"
            )

        ctx = {
            "platform": platform,
            "instance_id": kwargs.get("instance_id", ""),
            "user": kwargs.get("user", ""),
            "user_id": user_id,
            "user_avatar": user_avatar,
            "username": kwargs.get("username", ""),
            "time": kwargs.get("time"),
        }
        rich_header = kwargs.get("rich_header")
        attachments = _serialise_attachments(kwargs.get("attachments"))

        self._buffer_event(
            "chat.inbound",
            {
                "channel": _normalize_channel_addr(channel),
                "text": text,
                "message_id": message_id,
                "rich_header": rich_header,
                "attachments": attachments,
                **ctx,
            },
        )
        return message_id

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    # WS session
    # ------------------------------------------------------------------

    async def _session(self, url: str) -> None:
        headers = {
            "Authorization": f"Bearer {self.config.token}",
            "X-NextBridge-Instance": self.config.workbench_instance_id or "",
            "X-NextBridge-Version": self._version,
        }
        logger.info(f"Workbench [{self.instance_id}] connecting...")
        async with websockets.connect(
            url,
            additional_headers=headers,
            open_timeout=15,
            ping_interval=None,  # we run our own heartbeat
            max_size=2**20,
        ) as ws:
            self._ws = ws
            logger.info(f"Workbench [{self.instance_id}] connected")
            await self._send_json(
                {
                    "kind": "hello",
                    "instance_id": self.config.workbench_instance_id,
                    "instance_name": self.config.instance_name,
                    "version": self._version,
                    "command_prefix": self.bridge.command_prefix,
                }
            )

            await self._flush_buffer()

            heartbeat = asyncio.create_task(self._heartbeat_loop())
            pump = asyncio.create_task(self._pump_buffer())
            try:
                async for raw in ws:
                    await self._handle_incoming(raw)
            finally:
                heartbeat.cancel()
                pump.cancel()
                self._ws = None
                for task in (heartbeat, pump):
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

    async def _heartbeat_loop(self) -> None:
        interval = max(5, int(self.config.heartbeat_seconds))
        try:
            while True:
                await asyncio.sleep(interval)
                await self._send_json({"kind": "ping", "t": int(time.time())})
        except asyncio.CancelledError:
            return

    async def _pump_buffer(self) -> None:
        try:
            while True:
                event = await self._event_buffer.get()
                await self._send_json(event)
        except asyncio.CancelledError:
            return

    async def _flush_buffer(self) -> None:
        sent = 0
        while True:
            try:
                event = self._event_buffer.get_nowait()
            except asyncio.QueueEmpty:
                break
            await self._send_json(event)
            sent += 1
        if sent:
            logger.debug(
                f"Workbench [{self.instance_id}] flushed {sent} buffered event(s)"
            )

    # ------------------------------------------------------------------
    # Incoming frames
    # ------------------------------------------------------------------

    async def _handle_incoming(self, raw: str | bytes) -> None:
        try:
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            frame = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning(f"Workbench [{self.instance_id}] bad frame ({exc})")
            return

        kind = frame.get("kind")
        if kind == "ping":
            await self._send_json({"kind": "pong", "t": frame.get("t")})
            return
        if kind == "pong":
            return
        if kind != "req":
            logger.debug(
                f"Workbench [{self.instance_id}] ignoring frame kind={kind}"
            )
            return

        rpc_id = frame.get("id")
        method = frame.get("method", "")
        params = frame.get("params") or {}
        if not isinstance(params, dict):
            await self._send_response(rpc_id, ok=False, error="params must be an object")
            return

        handler = _RPC_METHODS.get(method)
        if handler is None:
            await self._send_response(
                rpc_id, ok=False, error=f"unknown method: {method}"
            )
            return

        try:
            result = handler(self, params)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            logger.opt(exception=exc).warning(
                f"Workbench [{self.instance_id}] RPC {method} failed"
            )
            await self._send_response(rpc_id, ok=False, error=str(exc))
            return

        await self._send_response(rpc_id, ok=True, data=result)

    # ------------------------------------------------------------------
    # Outgoing
    # ------------------------------------------------------------------

    async def _send_response(
        self,
        rpc_id: str | None,
        ok: bool,
        data: Any = None,
        error: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"kind": "res", "id": rpc_id, "ok": ok}
        if ok:
            payload["data"] = data
        else:
            payload["error"] = error or "unknown error"
        await self._send_json(payload)

    async def _send_json(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            return
        async with self._send_lock:
            try:
                await self._ws.send(
                    json.dumps(payload, ensure_ascii=False, default=str)
                )
            except Exception as exc:
                logger.debug(
                    f"Workbench [{self.instance_id}] send failed "
                    f"({type(exc).__name__}): {exc}"
                )
                try:
                    await self._ws.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Event buffering (shared by observer + send + chat.send)
    # ------------------------------------------------------------------

    def _matching_rule_ids(
        self, source_inst: str, source_channel: dict
    ) -> list[str]:
        """Find rule ids whose source matches this (instance_id, channel) pair.

        Forward rules: match against ``rule.from.<instance_id>``.
        Connect rules: match against ``rule.channels.<instance_id>``.
        Channel keys that aren't address fields (``msg``, ``webhook_url``)
        are ignored so format/webhook config doesn't break matching.
        """
        out: list[str] = []
        for rule in self.bridge.rules_snapshot():
            slot = "channels" if rule.get("type") == "connect" else "from"
            block = rule.get(slot)
            if not isinstance(block, dict):
                continue
            spec = block.get(source_inst)
            if not isinstance(spec, dict):
                continue
            ok = True
            for k, v in spec.items():
                if k in _NON_ADDRESS_KEYS:
                    continue
                if k not in source_channel:
                    continue
                if str(source_channel[k]) != str(v):
                    ok = False
                    break
            if ok:
                out.append(str(rule.get("id", "")))
        return out

    def _buffer_event(self, topic: str, data: dict) -> None:
        """Queue an event frame for delivery to the connected Workbench.

        Safe to call from sync or async contexts. If the queue is full
        the oldest entry is dropped so the tail stays current under load.
        """
        event = {
            "kind": "event",
            "topic": topic,
            "data": data,
            "t": int(time.time()),
        }
        try:
            self._event_buffer.put_nowait(event)
        except asyncio.QueueFull:
            try:
                _ = self._event_buffer.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                self._event_buffer.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def _on_bridge_event(self, topic: str, data: dict) -> Awaitable[None] | None:
        # Best-effort enrichment: tag bridge.message frames with the rule ids
        # they belong to, so Workbench's events table can show a "Group / Rule"
        # column without each consumer having to re-scan rules client-side.
        if topic == "bridge.message" and isinstance(data, dict):
            src_inst = data.get("instance_id")
            src_channel = data.get("channel")
            if isinstance(src_inst, str) and isinstance(src_channel, dict):
                matched = self._matching_rule_ids(src_inst, src_channel)
                if matched:
                    data = {**data, "rule_ids": matched}
        self._buffer_event(topic, data)
        return None


# ---------------------------------------------------------------------------
# CLI helpers — used by `python main.py workbench pair`
# ---------------------------------------------------------------------------


def _http_base(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower() or "https"
    if scheme not in ("http", "https"):
        scheme = "https"
    netloc = parsed.netloc or parsed.path
    if not netloc:
        raise SystemExit(f"Invalid workbench URL: {url}")
    return f"{scheme}://{netloc}"


def cmd_pair(
    workbench_url: str,
    code: str,
    instance_name: str | None,
    inst_id: str = "default",
) -> None:
    """Exchange a one-time pairing code for a long-lived token and write a
    ``workbench.<inst_id>`` block into the local config file."""
    base = _http_base(workbench_url)
    endpoint = f"{base}/api/nextbridge/pair"

    payload: dict[str, object] = {"code": code.strip()}
    if instance_name:
        payload["instance_name"] = instance_name.strip()

    logger.info(f"Pairing with Workbench at {endpoint}...")
    try:
        resp = httpx.post(endpoint, json=payload, timeout=20.0)
    except httpx.HTTPError as exc:
        logger.error(f"Failed to reach Workbench: {exc}")
        sys.exit(2)

    if resp.status_code >= 400:
        logger.error(f"Pairing failed ({resp.status_code}): {resp.text}")
        sys.exit(3)

    try:
        body = resp.json()
    except json.JSONDecodeError:
        logger.error(f"Workbench returned non-JSON: {resp.text[:200]}")
        sys.exit(3)

    token = body.get("token")
    wb_instance_id = body.get("instance_id")
    if not token or not wb_instance_id:
        logger.error(f"Workbench response missing token/instance_id: {body}")
        sys.exit(3)

    data_dir = Path(u.get_data_path())
    config_path = config_io.find_config(data_dir)
    if config_path is None:
        config_path = data_dir / "config.json"
        config: dict = {}
    else:
        config = config_io.load_config(config_path)

    wb_section = config.setdefault("workbench", {})
    if not isinstance(wb_section, dict):
        logger.error(
            "Existing `workbench` block in config is not a mapping; refusing to overwrite"
        )
        sys.exit(4)

    inst_block = wb_section.setdefault(inst_id, {})
    inst_block.update(
        {
            "url": base,
            "token": token,
            "workbench_instance_id": wb_instance_id,
            "instance_name": instance_name or inst_block.get("instance_name", ""),
        }
    )

    config_io.save_config(config, config_path)
    logger.info(
        f"Paired successfully. Instance id: {wb_instance_id}. "
        f"Config updated: {config_path}"
    )
    print(
        f"\nPaired with Workbench.\n"
        f"  url:                   {base}\n"
        f"  workbench instance_id: {wb_instance_id}\n"
        f"  local config key:      workbench.{inst_id}\n"
        f"  config file:           {config_path}\n\n"
        f"Restart NextBridge to bring the link up."
    )


register("workbench", WorkbenchConfig, WorkbenchDriver)
