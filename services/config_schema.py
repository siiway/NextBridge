from __future__ import annotations

from typing import Annotated, Literal
from os import environ

from pydantic import BaseModel, BeforeValidator, ConfigDict

import services.logger as log

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


def _get_proxy_from_env(v: str) -> str:
    if v.lower() in ["disabled", "disable"]:
        logger.debug("Global proxy disabled manually")
        return ""

    elif v:
        logger.debug(f"Using global proxy from config file: {v}")
        return v

    for env_var in ["http_proxy", "https_proxy", "all_proxy"]:
        env_value = environ.get(env_var) or environ.get(env_var.upper())
        if env_value:
            logger.debug(
                f"Using global proxy from environ variable {env_var}: {env_value}"
            )
            return env_value

    logger.debug("No global proxy configuration found")
    return ""


class DatabaseConfig(BaseModel):
    """Database configuration for SQLAlchemy.

    Supports multiple database backends via SQLAlchemy connection strings.
    Examples:
        - SQLite: sqlite:////path/to/database.db
        - MySQL: mysql+pymysql://user:password@host:port/database
        - PostgreSQL: postgresql://user:password@host:port/database
    """

    url: str = "sqlite:///data/messages.db"
    """SQLAlchemy database URL. Defaults to SQLite in the data directory."""

    echo: bool = False
    """Enable SQLAlchemy query logging for debugging."""

    pool_size: int | None = None
    """Connection pool size. Uses SQLAlchemy default if not specified."""

    max_overflow: int | None = None
    """Maximum overflow size of the pool. Uses SQLAlchemy default if not specified."""

    pool_recycle: int = 3600
    """Recycle connections after this many seconds (default: 1 hour)."""


class GlobalConfig(BaseModel):
    """Global configuration options that apply to all drivers unless overridden."""

    proxy: Annotated[str, BeforeValidator(_get_proxy_from_env)] = ""
    """Global proxy URL for all drivers that support proxy configuration.
    Individual driver proxy settings will override this global setting."""

    strict_echo_match: CoercedBool = False
    """Controls how the bridge prevents echoing messages back to the same channel/instance.

    When False (default): skips if target_id == msg.instance_id OR target_channel == msg.channel.
    When True: skips only if target_id == msg.instance_id AND target_channel == msg.channel.

    Default is False to maximize echo prevention."""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    """Console log verbosity level. The log file always captures DEBUG regardless.
    Set to DEBUG for verbose output during development or troubleshooting."""

    database: DatabaseConfig = DatabaseConfig()
    """Database configuration for message and user mappings."""


# ---------------------------------------------------------------------------
# Base for all driver config blocks — unknown keys are a validation error
# ---------------------------------------------------------------------------


class _DriverConfig(BaseModel):
    """Shared base for every per-driver config model.

    Sets ``extra="forbid"`` so typos in the config file are caught at startup
    rather than silently ignored.
    """

    model_config = ConfigDict(extra="forbid")
