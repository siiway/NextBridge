from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from datetime import datetime
from typing import Generator

import loguru
from loguru import logger

# ── ANSI colors (used by the custom console format function) ──
_RESET = "\033[0m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_RED_BOLD = "\033[1;31m"

_LEVEL_COLORS = {
    "TRACE": _DIM,
    "DEBUG": _DIM + _CYAN,
    "INFO": "",
    "WARNING": _YELLOW,
    "ERROR": _RED,
    "CRITICAL": _RED_BOLD,
}

_LEVEL_ICONS = {
    "TRACE": "TRC",
    "DEBUG": "DBG",
    "INFO": "INF",
    "WARNING": "WRN",
    "ERROR": "ERR",
    "CRITICAL": "CRT",
}

# ── Global state ──
LOG_DIR: str | None = None
LOG_FILE_PATH: str | None = None

LOG_ROTATION_SIZE = "100 MB"
LOG_RETENTION_DAYS = 7
LOG_COMPRESSION = "zip"
LOG_FILE_LEVEL = "DEBUG"

_console_id: int | None = None
_file_id: int | None = None

_sensitive: set[str] = set()

# "auto" → show source only for DEBUG/TRACE; "always" / "never"
_show_source_mode: str = "always"


# ── Sensitive value redaction ──


def register_sensitive(values: frozenset[str]) -> None:
    _sensitive.clear()
    _sensitive.update(v for v in values if len(v) >= 8)


def replace_sensitive(msg: str) -> str:
    if not _sensitive:
        return msg
    for secret in _sensitive:
        if secret in msg:
            msg = msg.replace(secret, "***")
    return msg


# ── Format callables ──


def _console_format(record: "loguru.Record") -> str:
    ts = record["time"].strftime("%Y-%m-%d %H:%M:%S")
    lvl_name = record["level"].name
    icon = _LEVEL_ICONS.get(lvl_name, lvl_name[:3].upper())
    lvl_color = _LEVEL_COLORS.get(lvl_name, "")
    msg = record["message"].replace("{", "{{").replace("}", "}}")

    source = record["extra"].get("source", "")
    show_source = record["extra"].get("_show_source", True)

    name = record["extra"].get("name", "")
    is_instance = record["extra"].get("_instance", False)
    name_color = _YELLOW if is_instance else _CYAN

    parts = [
        f"{_DIM}[{ts}]{_RESET}",
        f"{lvl_color}[{icon}]{_RESET}",
    ]
    if show_source and source:
        parts.append(f"| {_DIM}{source}{_RESET}")
    if name:
        parts.append(f"| {name_color}{name}{_RESET}")
    parts.append(f"| {msg}")

    result = " ".join(parts) + "\n"
    # Escape < to prevent loguru from parsing message content
    # (e.g. Discord emoji <:neuro:xxx>, source file <string>:N) as markup tags.
    # Two-step: protect existing \< first, then escape bare <.
    result = result.replace("\\<", "\\\\<")
    return result.replace("<", "\\<")


def _file_format(record: "loguru.Record") -> str:
    ts = record["time"].strftime("%Y-%m-%d %H:%M:%S")
    lvl_name = record["level"].name
    icon = _LEVEL_ICONS.get(lvl_name, lvl_name[:3].upper())
    msg = record["message"].replace("{", "{{").replace("}", "}}")
    source = record["extra"].get("source", "")
    name = record["extra"].get("name", "")
    exc = record["exception"]
    parts = [
        f"[{ts}]",
        f"[{icon}]",
    ]
    if source:
        parts.append(f"| {source}")
    if name:
        parts.append(f"| {name}")
    parts.append(f"| {msg}")
    if exc:
        parts.append(str(exc))
    result = " ".join(parts) + "\n"
    result = result.replace("\\<", "\\\\<")
    return result.replace("<", "\\<")


def _masking_filter(record: "loguru.Record") -> bool:
    if record.get("extra", {}).get("_uvicorn"):
        record["extra"]["source"] = ""
        record["extra"]["name"] = "uvicorn"
    else:
        if "source" not in record.get("extra", {}):
            record["extra"]["source"] = f"{record['file'].name}:{record['line']}"
        if "name" not in record.get("extra", {}):
            record["extra"]["name"] = ""

    # Determine whether to show source file location
    if "source" in record.get("extra", {}):
        override = record["extra"].get("_show_source_override")
        mode = override if override is not None else _show_source_mode
        if mode == "always":
            record["extra"]["_show_source"] = True
        elif mode == "never":
            record["extra"]["_show_source"] = False
        else:  # "auto"
            record["extra"]["_show_source"] = (
                record["level"].no <= logger.level("DEBUG").no
            )

    if _sensitive:
        msg = record["message"]
        msg = replace_sensitive(msg)
        record["message"] = msg

    return True


# ── Level icons ──
logger.level("TRACE", icon="TRC")
logger.level("DEBUG", icon="DBG")
logger.level("INFO", icon="INF")
logger.level("WARNING", icon="WRN")
logger.level("ERROR", icon="ERR")
logger.level("CRITICAL", icon="CRT")

# ── Remove default sink ──
logger.remove()

# ── Console sink ──
_console_id = logger.add(
    sys.stdout,
    level="INFO",
    format=_console_format,
    filter=_masking_filter,
)


# ── Public API ──


def get_logger(name: str = "", instance: bool = False) -> "loguru.Logger":
    """Return a logger bound with *name* as the context prefix.

    Args:
        name: The prefix name to show in log output.
        instance: If True, marks as a driver instance logger (yellow prefix).
    """
    if name:
        return logger.bind(name=name, _instance=instance)
    return logger


@contextmanager
def log_context(ctx: str) -> Generator[None, None, None]:
    """Temporarily add extra context to the current logger scope.

    Usage::

        with log_context("upload"):
            logger.info("starting...")
    """
    with logger.contextualize(_context=ctx):
        yield


def set_log_dir(log_dir: str | None) -> None:
    global LOG_DIR, LOG_FILE_PATH, _file_id

    if _file_id is not None:
        logger.remove(_file_id)
        _file_id = None

    LOG_DIR = log_dir
    if LOG_DIR is not None:
        os.makedirs(LOG_DIR, exist_ok=True)
        _log_filename = datetime.now().strftime("%Y%m%d-%H%M%S%f")[:-3] + ".log"
        LOG_FILE_PATH = os.path.join(LOG_DIR, _log_filename)
        _file_id = logger.add(
            LOG_FILE_PATH,
            level=LOG_FILE_LEVEL,
            format=_file_format,
            encoding="utf-8",
            filter=_masking_filter,
            rotation=LOG_ROTATION_SIZE,
            retention=f"{LOG_RETENTION_DAYS} days",
            compression=LOG_COMPRESSION,
        )
    else:
        LOG_FILE_PATH = None


def set_log_rotation(
    rotation_size: str | None = None,
    retention_days: int | None = None,
    compression: str | None = None,
    file_level: str | None = None,
) -> None:
    global \
        LOG_ROTATION_SIZE, \
        LOG_RETENTION_DAYS, \
        LOG_COMPRESSION, \
        LOG_FILE_LEVEL, \
        _file_id

    if rotation_size is not None:
        LOG_ROTATION_SIZE = rotation_size
    if retention_days is not None:
        LOG_RETENTION_DAYS = retention_days
    if compression is not None:
        LOG_COMPRESSION = compression
    if file_level is not None:
        LOG_FILE_LEVEL = file_level

    if _file_id is not None and LOG_DIR is not None:
        logger.remove(_file_id)
        _file_id = None
        _log_filename = datetime.now().strftime("%Y%m%d-%H%M%S%f")[:-3] + ".log"
        LOG_FILE_PATH = os.path.join(LOG_DIR, _log_filename)
        _file_id = logger.add(
            LOG_FILE_PATH,
            level="DEBUG",
            format=_file_format,
            encoding="utf-8",
            filter=_masking_filter,
            rotation=LOG_ROTATION_SIZE,
            retention=f"{LOG_RETENTION_DAYS} days",
            compression=LOG_COMPRESSION,
        )


def set_console_level(level: str) -> None:
    global _console_id
    logger.remove(_console_id)
    _console_id = logger.add(
        sys.stdout,
        level=level,
        format=_console_format,
        filter=_masking_filter,
    )
    logger.debug(f"Console log level set to: {level}")


def set_show_source(mode: str) -> None:
    """Control whether the source file location is shown in log output.

    Args:
        mode: ``"auto"`` (show only for DEBUG/TRACE), ``"always"``, or ``"never"``.
    """
    global _show_source_mode
    if mode not in ("auto", "always", "never"):
        raise ValueError(f"Invalid show_source mode: {mode!r}")
    _show_source_mode = mode
