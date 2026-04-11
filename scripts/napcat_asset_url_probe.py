#!/usr/bin/env python3
"""Probe QQ/NapCat asset URL expiry and re-fetch behavior.

This script helps validate the hypothesis:
- QQ CDN asset URLs may expire after some time.
- Re-calling NapCat message-fetch APIs may return fresh URLs.

Supported fetch modes:
- forward: action `get_forward_msg` with params {"id": <target_id>}
- msg:     action `get_msg` with params {"message_id": <target_id>}

Example:
  uv run scripts/napcat_asset_url_probe.py \
    --ws-url ws://127.0.0.1:3001 \
    --ws-token your_token \
    --mode forward \
    --id 1987654321 \
    --interval 120 \
    --max-rounds 30
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp
import websockets


@dataclass(slots=True)
class AssetEntry:
    key: str
    seg_type: str
    url: str
    path: str


class NapCatClient:
    def __init__(self, ws_url: str, ws_token: str = ""):
        if ws_token:
            sep = "&" if "?" in ws_url else "?"
            ws_url = f"{ws_url}{sep}access_token={ws_token}"
        self.ws_url = ws_url
        self._connect_kwargs = {
            "ping_interval": None,
            "ping_timeout": None,
            "close_timeout": 5,
            "open_timeout": 10,
        }

    async def call(
        self, action: str, params: dict[str, Any], timeout: float
    ) -> dict[str, Any] | None:
        echo = str(uuid.uuid4())
        payload = {"action": action, "params": params, "echo": echo}

        async with websockets.connect(self.ws_url, **self._connect_kwargs) as ws:
            await ws.send(json.dumps(payload, ensure_ascii=False))

            deadline = asyncio.get_running_loop().time() + timeout
            while True:
                remain = deadline - asyncio.get_running_loop().time()
                if remain <= 0:
                    return None
                raw = await asyncio.wait_for(ws.recv(), timeout=remain)
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if data.get("echo") == echo:
                    return data


def _segment_url(seg_data: dict[str, Any]) -> str:
    value = (
        seg_data.get("url")
        or seg_data.get("src")
        or seg_data.get("path")
        or seg_data.get("file")
        or ""
    )
    text = str(value).strip()
    if text.startswith(("http://", "https://")):
        return text
    return ""


def _segment_key(seg_type: str, seg_data: dict[str, Any], path: str, idx: int) -> str:
    for k in ("file_unique", "file_id", "id", "md5", "fid", "name", "file"):
        v = str(seg_data.get(k, "")).strip()
        if v:
            return f"{seg_type}:{k}:{v}"
    return f"{seg_type}:path:{path}#{idx}"


def _iter_forward_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = payload.get("messages")
    if nodes is None:
        nodes = payload.get("message")
    return nodes if isinstance(nodes, list) else []


def _iter_msg_segments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    message = payload.get("message")
    return message if isinstance(message, list) else []


def collect_assets(payload: dict[str, Any], mode: str) -> list[AssetEntry]:
    out: list[AssetEntry] = []

    def walk_segments(segments: list[dict[str, Any]], parent_path: str) -> None:
        for i, seg in enumerate(segments):
            seg_type = str(seg.get("type", "")).strip()
            seg_data = seg.get("data") or {}
            if not isinstance(seg_data, dict):
                continue

            path = f"{parent_path}/seg[{i}]"
            if seg_type in {"image", "mface", "record", "video", "file"}:
                u = _segment_url(seg_data)
                if u:
                    out.append(
                        AssetEntry(
                            key=_segment_key(seg_type, seg_data, parent_path, i),
                            seg_type=seg_type,
                            url=u,
                            path=path,
                        )
                    )

            if seg_type == "forward":
                nested = None
                for key in ("content", "messages", "message"):
                    value = seg_data.get(key)
                    if isinstance(value, list):
                        nested = value
                        break
                if isinstance(nested, list):
                    walk_segments(nested, f"{path}/forward")

    if mode == "forward":
        nodes = _iter_forward_nodes(payload)
        for n_idx, node in enumerate(nodes):
            content = node.get("content")
            if content is None:
                content = node.get("message")
            if content is None and isinstance(node.get("data"), dict):
                data = node.get("data") or {}
                content = data.get("content") or data.get("message")
            if isinstance(content, list):
                walk_segments(content, f"node[{n_idx}]")
    else:
        walk_segments(_iter_msg_segments(payload), "msg")

    dedup: dict[str, AssetEntry] = {}
    for item in out:
        dedup[item.key] = item
    return list(dedup.values())


async def probe_url(
    session: aiohttp.ClientSession, url: str, timeout: float
) -> dict[str, Any]:
    expired_errno = "-5503007"

    def _looks_expired_text(text: str) -> bool:
        t = (text or "").lower()
        return (
            "download url has expired" in t
            or "download_url_has_expired" in t
            or '"retcode":-5503007' in t
            or '"retcode": -5503007' in t
        )

    def _header_errno(headers: Any) -> str:
        # QQ responses may use X-ErrNo (case-insensitive)
        for key in ("X-ErrNo", "x-errno", "x-errNo"):
            value = headers.get(key)
            if value is not None:
                return str(value).strip()
        return ""

    result: dict[str, Any] = {
        "ok": False,
        "status": None,
        "reason": "unknown",
    }

    try:
        async with session.head(
            url,
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            result["status"] = resp.status
            result["x_errno"] = _header_errno(resp.headers)
            ct = (resp.headers.get("Content-Type") or "").lower()
            if 200 <= resp.status < 400:
                result["ok"] = True
                result["reason"] = f"head-{resp.status}"
                return result
            if resp.status == 400 and result.get("x_errno") == expired_errno:
                result["reason"] = "expired-errno-head"
                return result
            if "json" in ct:
                body = (await resp.text()).strip()
                if _looks_expired_text(body):
                    result["reason"] = "expired-json-head"
                else:
                    result["reason"] = f"head-{resp.status}-json"
            else:
                result["reason"] = f"head-{resp.status}"
    except Exception as exc:
        result["reason"] = f"head-exception:{type(exc).__name__}"

    try:
        async with session.get(
            url,
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=timeout),
            headers={"Range": "bytes=0-511"},
        ) as resp:
            result["status"] = resp.status
            result["x_errno"] = _header_errno(resp.headers)
            ct = (resp.headers.get("Content-Type") or "").lower()
            body = (await resp.content.read(1024)).decode(errors="ignore")

            if resp.status == 400 and result.get("x_errno") == expired_errno:
                result["reason"] = "expired-errno-get"
                return result

            if 200 <= resp.status < 400 and not _looks_expired_text(body):
                result["ok"] = True
                result["reason"] = f"get-{resp.status}"
                return result

            if _looks_expired_text(body):
                result["reason"] = "expired-json-get"
            else:
                result["reason"] = f"get-{resp.status}-{ct[:40]}"
            return result
    except Exception as exc:
        result["reason"] = f"get-exception:{type(exc).__name__}"
        return result


def fetch_request(mode: str, target_id: str) -> tuple[str, dict[str, Any]]:
    if mode == "forward":
        return "get_forward_msg", {"id": target_id}
    return "get_msg", {"message_id": target_id}


def print_assets(label: str, assets: list[AssetEntry]) -> None:
    print(f"\n[{label}] assets={len(assets)}")
    for a in assets:
        print(f"- {a.key} ({a.seg_type})")
        print(f"  path={a.path}")
        print(f"  url={a.url}")


def _fmt_local_time(ts: int) -> str:
    return (
        datetime.datetime.fromtimestamp(ts)
        .astimezone()
        .strftime("%Y-%m-%d %H:%M:%S %z")
    )


async def _notify_qq_report(
    nc: NapCatClient,
    qq: str,
    timeout: float,
    report: dict[str, Any],
    out_path: str,
) -> None:
    qq_text = str(qq or "").strip()
    if not qq_text:
        return

    started_at = int(report.get("started_at") or 0)
    ended_at = int(report.get("ended_at") or time.time())
    rounds = len(report.get("rounds") or [])

    lines = [
        "[napcat-asset-probe] 探测完成",
        f"启动时间: {_fmt_local_time(started_at)}",
        f"结束时间: {_fmt_local_time(ended_at)}",
        f"模式: {report.get('mode', '')}",
        f"目标ID: {report.get('target_id', '')}",
        f"结果: {report.get('result', '')}",
        f"轮次: {rounds}",
        f"耗时: {report.get('duration_seconds', 0)} 秒",
    ]
    if out_path:
        lines.append(f"报告: {out_path}")

    message = "\n".join(lines)

    user_id: int | str
    try:
        user_id = int(qq_text)
    except ValueError:
        user_id = qq_text

    resp = await nc.call(
        "send_private_msg",
        {"user_id": user_id, "message": message},
        timeout=timeout,
    )
    if not resp or resp.get("status") != "ok":
        print(f"[warn] notify qq failed: {resp}")


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe NapCat asset URL expiry behavior"
    )
    parser.add_argument(
        "--ws-url", required=True, help="NapCat websocket URL, e.g. ws://127.0.0.1:3001"
    )
    parser.add_argument("--ws-token", default="", help="NapCat access token")
    parser.add_argument("--mode", choices=["forward", "msg"], default="forward")
    parser.add_argument(
        "--id", required=True, help="Forward ID (mode=forward) or message_id (mode=msg)"
    )
    parser.add_argument(
        "--interval", type=float, default=60.0, help="Seconds between probe rounds"
    )
    parser.add_argument(
        "--max-rounds", type=int, default=30, help="Maximum probe rounds"
    )
    parser.add_argument(
        "--action-timeout", type=float, default=30.0, help="Timeout for NapCat actions"
    )
    parser.add_argument(
        "--probe-timeout",
        type=float,
        default=12.0,
        help="Timeout for URL probe requests",
    )
    parser.add_argument("--out", default="", help="Optional JSON report path")
    parser.add_argument(
        "--notify-qq",
        default="",
        help="Optional QQ number to receive final report via send_private_msg",
    )
    parser.add_argument(
        "--notify-timeout",
        type=float,
        default=20.0,
        help="Timeout for QQ notification action",
    )
    args = parser.parse_args()

    report: dict[str, Any] = {
        "started_at": int(time.time()),
        "mode": args.mode,
        "target_id": args.id,
        "rounds": [],
        "result": "unknown",
    }

    action, params = fetch_request(args.mode, args.id)

    nc = NapCatClient(args.ws_url, args.ws_token)
    first = await nc.call(action, params, timeout=args.action_timeout)
    if not first or first.get("status") != "ok":
        print(f"[fatal] first {action} failed: {first}")
        report["result"] = "fetch-failed"
        report["ended_at"] = int(time.time())
        report["duration_seconds"] = report["ended_at"] - report["started_at"]
        if args.out:
            Path(args.out).write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        if args.notify_qq:
            await _notify_qq_report(
                nc, args.notify_qq, args.notify_timeout, report, args.out
            )
        return 2

    first_payload = first.get("data") or {}
    baseline = collect_assets(first_payload, args.mode)
    if not baseline:
        print("[fatal] no asset urls found in payload")
        report["result"] = "no-assets"
        report["ended_at"] = int(time.time())
        report["duration_seconds"] = report["ended_at"] - report["started_at"]
        if args.out:
            Path(args.out).write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        if args.notify_qq:
            await _notify_qq_report(
                nc, args.notify_qq, args.notify_timeout, report, args.out
            )
        return 3

    print_assets("baseline", baseline)
    baseline_by_key = {a.key: a for a in baseline}

    async with aiohttp.ClientSession() as session:
        for round_no in range(1, args.max_rounds + 1):
            await asyncio.sleep(args.interval)
            print(f"\n[round {round_no}] probing {len(baseline_by_key)} urls...")
            round_info: dict[str, Any] = {
                "round": round_no,
                "at": int(time.time()),
                "checks": [],
                "expired_keys": [],
                "refetch": None,
            }

            expired_keys: list[str] = []
            for key, asset in baseline_by_key.items():
                status = await probe_url(session, asset.url, timeout=args.probe_timeout)
                check_row = {
                    "key": key,
                    "seg_type": asset.seg_type,
                    "url": asset.url,
                    "status": status,
                }
                round_info["checks"].append(check_row)
                ok = bool(status.get("ok"))
                print(
                    f"  - {key}: ok={ok} reason={status.get('reason')} status={status.get('status')}"
                )
                if not ok:
                    expired_keys.append(key)

            round_info["expired_keys"] = expired_keys

            if expired_keys:
                print(
                    f"[round {round_no}] detected expired/unavailable keys: {expired_keys}"
                )
                fresh = await nc.call(action, params, timeout=args.action_timeout)
                if not fresh or fresh.get("status") != "ok":
                    print(f"[round {round_no}] refetch failed: {fresh}")
                    round_info["refetch"] = {"ok": False, "response": fresh}
                    report["rounds"].append(round_info)
                    report["result"] = "expired-but-refetch-failed"
                    break

                fresh_assets = collect_assets(fresh.get("data") or {}, args.mode)
                fresh_by_key = {a.key: a for a in fresh_assets}

                refreshed: list[dict[str, Any]] = []
                any_changed = False
                for key in expired_keys:
                    before = baseline_by_key.get(key)
                    after = fresh_by_key.get(key)
                    row = {
                        "key": key,
                        "before": before.url if before else "",
                        "after": after.url if after else "",
                        "changed": bool(before and after and before.url != after.url),
                        "missing_after_refetch": after is None,
                    }
                    if row["changed"] and after:
                        any_changed = True
                        baseline_by_key[key] = after
                    refreshed.append(row)

                round_info["refetch"] = {
                    "ok": True,
                    "changed": any_changed,
                    "details": refreshed,
                }

                print("[refetch compare]")
                for row in refreshed:
                    print(
                        "  - {key}: changed={changed} missing_after_refetch={missing}".format(
                            key=row["key"],
                            changed=row["changed"],
                            missing=row["missing_after_refetch"],
                        )
                    )

                report["rounds"].append(round_info)
                report["result"] = (
                    "expired-and-refetched-with-new-urls"
                    if any_changed
                    else "expired-but-refetch-did-not-refresh"
                )
                break

            report["rounds"].append(round_info)

        if report["result"] == "unknown":
            report["result"] = "no-expiry-detected-within-window"

    report["ended_at"] = int(time.time())
    report["duration_seconds"] = report["ended_at"] - report["started_at"]

    print(f"\n[result] {report['result']}")
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[report] wrote: {out_path}")

    if args.notify_qq:
        await _notify_qq_report(
            nc, args.notify_qq, args.notify_timeout, report, args.out
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
