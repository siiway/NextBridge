from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import loguru
import services.logger as log
from loguru import logger

AUDIT_LEVEL = "AUDIT"
"""Custom loguru level used exclusively by the audit sink."""

_TRUNCATE_LIMIT = 500
_sink_id: int | None = None
_event_bus: Any = None

try:
    logger.level(AUDIT_LEVEL, no=25, color="<yellow>", icon="AUD")
except ValueError:
    pass


def _audit_format(record: "loguru.Record") -> str:
    entry = record["extra"].get("audit", {})
    text = json.dumps(entry, ensure_ascii=False, default=str)
    # loguru treats the callable's return value as a format template, so
    # escape braces to keep the JSON literal intact.
    text = text.replace("{", "{{").replace("}", "}}")
    return log.replace_sensitive(text) + "\n"


def _audit_filter(record: "loguru.Record") -> bool:
    return "audit" in record["extra"]


def _truncate(value: Any, limit: int = _TRUNCATE_LIMIT) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + "..."


def configure(
    log_dir: str | None,
    *,
    rotation: str | None = "100 MB",
    retention: int = 7,
    compression: str | None = "zip",
    event_bus: Any = None,
) -> bool:
    """Install the audit file sink under *log_dir*/audit.log.

    Returns ``True`` when a sink was installed.  When *log_dir* is falsy the
    file sink is removed and audit entries are only emitted on the event bus.
    """
    global _sink_id, _event_bus

    _event_bus = event_bus

    if _sink_id is not None:
        logger.remove(_sink_id)
        _sink_id = None

    if not log_dir:
        return False

    os.makedirs(log_dir, exist_ok=True)
    _sink_id = logger.add(
        str(Path(log_dir) / "audit.log"),
        level=AUDIT_LEVEL,
        format=_audit_format,
        filter=_audit_filter,
        encoding="utf-8",
        rotation=rotation,
        retention=f"{retention} days" if retention else None,
        compression=compression,
    )
    return True


def record(
    event: str,
    *,
    actor: str = "",
    source_ip: str = "",
    target: str = "",
    before: Any = None,
    after: Any = None,
    result: str = "ok",
    error: str = "",
) -> dict:
    """Append a structured audit entry and emit it on the event bus.

    Returns the entry that was written so callers can reuse it in responses.
    """
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "actor": actor,
        "source_ip": source_ip,
        "target": target,
        "before": _truncate(before),
        "after": _truncate(after),
        "result": result,
        "error": error,
    }
    logger.bind(audit=entry).log(AUDIT_LEVEL, "")

    if _event_bus is not None:
        payload = {k: v for k, v in entry.items() if k != "event"}
        try:
            _event_bus.emit(f"audit.{event}", **payload)
        except Exception:
            pass

    return entry
