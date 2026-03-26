import sys
import os
from datetime import datetime

import loguru
from loguru import logger

# Global log configuration
LOG_DIR = None  # Set to a directory path to enable file logging, or None to disable file logging
LOG_FILE_PATH = None

# Log rotation configuration
LOG_ROTATION_SIZE = "100 MB"  # Maximum size of a single log file before rotation
LOG_RETENTION_DAYS = 7  # Number of days to keep log files
LOG_COMPRESSION = "zip"  # Compression format for rotated log files (None to disable)

# Log levels
LOG_FILE_LEVEL = "DEBUG"  # File log level (default: DEBUG)

# File sink ID for dynamic management
_file_id: int | None = None


# Sensitive strings to redact from all log output.
# Populated by register_sensitive() after the config is loaded.
_sensitive: set[str] = set()


def register_sensitive(values: frozenset[str]) -> None:
    """Register secret strings that must never appear in log output."""
    _sensitive.clear()
    # Skip values shorter than 8 chars to avoid masking common substrings
    _sensitive.update(v for v in values if len(v) >= 8)


# this shouldn't be in log, move out if there's better place
def replace_sensitive(msg: str) -> str:
    """Return a redacted version of msg, with all registered secrets replaced."""
    if not _sensitive:
        return msg
    for secret in _sensitive:
        if secret in msg:
            msg = msg.replace(secret, "***")
    return msg
def _masking_filter(record: "loguru.Record") -> bool:
    """Redact sensitive values from every log record before emission."""
    if _sensitive:
        msg = record["message"]
        msg = replace_sensitive(msg)
        record["message"] = msg
    return True

# Custom logging level icons
logger.level("TRACE", icon="TRC")
logger.level("DEBUG", icon="DBG")
logger.level("INFO", icon="INF")
logger.level("WARNING", icon="WRN")
logger.level("ERROR", icon="ERR")
logger.level("CRITICAL", icon="CRT")

_CONSOLE_FORMAT = (
    "<dim>[{time:YYYY-MM-DD HH:mm:ss}]</dim> "
    "<level>[{level.icon}]</level> "
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
# File sink will be added when set_log_dir() is called with a valid directory


def get_logger():
    return logger


def set_log_dir(log_dir: str | None) -> None:
    """Set the log directory at runtime.

    Args:
        log_dir: Path to the log directory. If None or empty, file logging will be disabled.
    
    Call this once after the config is loaded.
    """
    global LOG_DIR, LOG_FILE_PATH, _file_id
    
    # Remove existing file sink if any
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
            format=_FILE_FORMAT,
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
    """Set log rotation parameters at runtime.

    Args:
        rotation_size: Maximum size of a single log file before rotation (e.g., "100 MB").
            If None, uses the current value.
        retention_days: Number of days to keep log files. If None, uses the current value.
        compression: Compression format for rotated log files (e.g., "zip", "gz", "tar.gz").
            If None, uses the current value.
        file_level: File log level (e.g., "DEBUG", "INFO"). If None, uses the current value.

    Call this once after the config is loaded. Changes take effect on next rotation.
    """
    global LOG_ROTATION_SIZE, LOG_RETENTION_DAYS, LOG_COMPRESSION, LOG_FILE_LEVEL, _file_id

    if rotation_size is not None:
        LOG_ROTATION_SIZE = rotation_size
    if retention_days is not None:
        LOG_RETENTION_DAYS = retention_days
    if compression is not None:
        LOG_COMPRESSION = compression
    if file_level is not None:
        LOG_FILE_LEVEL = file_level

    # Reconfigure file sink if it exists
    if _file_id is not None and LOG_DIR is not None:
        logger.remove(_file_id)
        _file_id = None
        _log_filename = datetime.now().strftime("%Y%m%d-%H%M%S%f")[:-3] + ".log"
        LOG_FILE_PATH = os.path.join(LOG_DIR, _log_filename)
        _file_id = logger.add(
            LOG_FILE_PATH,
            level="DEBUG",
            format=_FILE_FORMAT,
            encoding="utf-8",
            filter=_masking_filter,
            rotation=LOG_ROTATION_SIZE,
            retention=f"{LOG_RETENTION_DAYS} days",
            compression=LOG_COMPRESSION,
        )


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
