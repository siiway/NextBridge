import sys
import os
from datetime import datetime

import loguru
from loguru import logger

# Log file output directory
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

_log_filename = datetime.now().strftime("%Y%m%d-%H%M%S%f")[:-3] + ".log"
LOG_FILE_PATH = os.path.join(LOG_DIR, _log_filename)


# Sensitive strings to redact from all log output.
# Populated by register_sensitive() after the config is loaded.
_sensitive: set[str] = set()


def register_sensitive(values: frozenset[str]) -> None:
    """Register secret strings that must never appear in log output."""
    _sensitive.clear()
    # Skip values shorter than 8 chars to avoid masking common substrings
    _sensitive.update(v for v in values if len(v) >= 8)


def _masking_filter(record: loguru.Record) -> bool:
    """Redact sensitive values from every log record before emission."""
    if _sensitive:
        msg = record["message"]
        for secret in _sensitive:
            if secret in msg:
                msg = msg.replace(secret, "***")
        record["message"] = msg
    return True


_CONSOLE_FORMAT = (
    "<dim>[{time:YYYY-MM-DD HH:mm:ss}]</dim> "
    "<level>[{level.name:.3}]</level> "
    "| <dim>{file}:{line}</dim> | {message}"
)
_FILE_FORMAT = (
    "[{time:YYYY-MM-DD HH:mm:ss}] [{level}] | {file}:{line} | {message}{exception}"
)

# Remove loguru's default stderr sink
logger.remove()

# Console sink — level is configurable at runtime via set_console_level()
_console_id: int = logger.add(
    sys.stdout,
    level="INFO",
    format=_CONSOLE_FORMAT,
    colorize=True,
    filter=_masking_filter,
)

# File sink — always DEBUG so nothing is ever lost
logger.add(
    LOG_FILE_PATH,
    level="DEBUG",
    format=_FILE_FORMAT,
    encoding="utf-8",
    filter=_masking_filter,
)


def get_logger():
    return logger


def set_console_level(level: str) -> None:
    """Set the console handler's log level at runtime.

    Accepts standard level names: DEBUG, INFO, WARNING, ERROR, CRITICAL.
    The file sink always retains DEBUG so nothing is lost.
    Call this once after the config is loaded.
    """
    global _console_id
    logger.remove(_console_id)
    _console_id = logger.add(
        sys.stdout,
        level=level,
        format=_CONSOLE_FORMAT,
        colorize=True,
        filter=_masking_filter,
    )
    logger.debug(f"Console log level set to: {level}")
