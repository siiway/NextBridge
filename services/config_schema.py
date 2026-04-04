from __future__ import annotations

from os import environ
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, field_validator

import services.logger as log

UNSET = "unset"
logger = log.get_logger()

# ---------------------------------------------------------------------------
# Reusable bool coercion: "true" / "1" / "yes" → True
# ---------------------------------------------------------------------------


def _coerce_bool(v: object) -> object:
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes")
    return v


CoercedBool = Annotated[bool, BeforeValidator(_coerce_bool)]


# ---------------------------------------------------------------------------
# Global configuration
# ---------------------------------------------------------------------------


class DatabaseConfig(BaseModel):
    """Database configuration for SQLAlchemy.

    Supports multiple database backends via SQLAlchemy connection strings.
    Examples:
        - SQLite: sqlite:////path/to/database.db
        - MySQL: mysql+pymysql://user:password@host:port/database
        - PostgreSQL: postgresql://user:password@host:port/database
    """

    url: str = "sqlite:///messages.db"
    """SQLAlchemy database URL. Relative SQLite paths are resolved under the data directory."""

    echo: bool = False
    """Enable SQLAlchemy query logging for debugging."""

    pool_size: int | None = None
    """Connection pool size. Uses SQLAlchemy default if not specified."""

    max_overflow: int | None = None
    """Maximum overflow size of the pool. Uses SQLAlchemy default if not specified."""

    pool_recycle: int = 3600
    """Recycle connections after this many seconds (default: 1 hour)."""


class LoggingConfig(BaseModel):
    """Logging configuration for controlling log output and rotation."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    """Console log verbosity level.
    Set to DEBUG for verbose output during development or troubleshooting."""

    file_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "DEBUG"
    """File log verbosity level. Default is DEBUG to capture all log messages."""

    dir: str | None = "logs"
    """Directory path for log files. If None or empty, file logging is disabled.
    Log files are automatically created with timestamp-based names."""

    rotation_size: str = "100 MB"
    """Maximum size of a single log file before rotation (e.g., "100 MB", "500 MB").
    Log files are automatically rotated when they exceed this size."""

    retention_days: int = 7
    """Number of days to keep log files. Older log files are automatically deleted.
    Set to 0 to disable automatic deletion."""

    compression: (
        Literal["gz", "bz2", "xz", "lzma", "tar", "tar.gz", "tar.bz2", "tar.xz", "zip"]
        | None
    ) = "zip"
    """Compression format for rotated log files (e.g., "zip", "gz", "tar.gz").
    Set to None to disable compression."""

    @field_validator("level", "file_level", mode="before")
    def normalize_level(cls, v):
        if v is None:
            return v
        if not isinstance(v, str):
            raise ValueError(f"Invaild log level: {v}")
        upper = v.strip().upper()
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if upper not in valid:
            raise ValueError(f"Invaild log level: {v}")
        return upper


class GlobalConfig(BaseModel):
    """Global configuration options that apply to all drivers unless overridden."""

    command_prefix: str = "nb"
    """Prefix used for built-in bridge commands, e.g. ``/nb bind setup``.

    The value is written without the leading slash. The default is ``nb``.
    """

    proxy: str | None = UNSET
    """Global proxy URL for all drivers that support proxy configuration.
    Individual driver proxy settings will override this global setting."""

    strict_echo_match: CoercedBool = False
    """Controls how the bridge prevents echoing messages back to the same channel/instance.

    When False (default): skips if target_id == msg.instance_id OR target_channel == msg.channel.
    When True: skips only if target_id == msg.instance_id AND target_channel == msg.channel.

    Default is False to maximize echo prevention."""

    log: LoggingConfig = LoggingConfig()
    """Logging configuration for controlling log output and rotation."""

    database: DatabaseConfig = DatabaseConfig()
    """Database configuration for message and user mappings."""

    @field_validator("command_prefix", mode="before")
    def normalize_command_prefix(cls, v):
        if v is None:
            return "nb"
        if not isinstance(v, str):
            raise ValueError(f"Invalid command prefix: {v}")
        prefix = v.strip().lstrip("/")
        if not prefix:
            raise ValueError("command_prefix cannot be empty")
        return prefix

    @field_validator("proxy", mode="after")
    def get_proxy_from_env(cls, v: str):
        if v.lower() in ["disabled", "disable", "unset"]:
            logger.debug("Global proxy disabled manually")
            return None

        elif v:
            logger.debug(f"Using global proxy from config file: {v}")
            return v or None

        for env_var in ["http_proxy", "https_proxy", "all_proxy"]:
            env_value = environ.get(env_var) or environ.get(env_var.upper())
            if env_value:
                logger.debug(
                    f"Using global proxy from environ variable {env_var}: {env_value}"
                )
                return env_value or None

        logger.debug("No global proxy configuration found")
        return None


# ---------------------------------------------------------------------------
# Base for all driver config blocks — unknown keys are a validation error
# ---------------------------------------------------------------------------


class _DriverConfig(BaseModel):
    """Shared base for every per-driver config model.

    Sets ``extra="forbid"`` so typos in the config file are caught at startup
    rather than silently ignored.
    """

    model_config = ConfigDict(extra="forbid")
