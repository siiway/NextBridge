from __future__ import annotations

from os import environ
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

import services.logger as log

UNSET = "unset"
logger = log.get_logger("config_schema")

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

    url: str = "sqlite:///data.db"
    """SQLAlchemy database URL. Relative SQLite paths are resolved under the data directory."""

    echo: bool = False
    """Enable SQLAlchemy query logging for debugging."""

    pool_size: int | None = None
    """Connection pool size. Uses SQLAlchemy default if not specified."""

    max_overflow: int | None = None
    """Maximum overflow size of the pool. Uses SQLAlchemy default if not specified."""

    pool_recycle: int = 3600
    """Recycle connections after this many seconds (default: 1 hour)."""

    sslmode: str | None = None
    """PostgreSQL SSL mode (e.g. ``require``, ``prefer``, ``disable``).
    Only applies to PostgreSQL backends."""

    connect_timeout: int | None = None
    """PostgreSQL connection timeout in seconds.
    Only applies to PostgreSQL backends."""

    application_name: str | None = None
    """PostgreSQL application name for connection identification.
    Only applies to PostgreSQL backends."""


class LoggingConfig(BaseModel):
    """Logging configuration for controlling log output and rotation."""

    show_source: Literal["auto", "always", "never"] = "auto"
    """Controls whether source file locations are shown in logs.

    - ``auto``: show source only for DEBUG/TRACE level messages.
    - ``always``: always show source.
    - ``never``: never show source.
    """

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


class HttpConfig(BaseModel):
    """Shared HTTP server configuration for mounted driver webhooks."""

    host: str = "0.0.0.0"
    """Host/IP for the shared HTTP server."""

    port: int = 9080
    """Port for the shared HTTP server."""

    root_path: str = ""
    """Optional ASGI root_path, useful behind path-prefixed reverse proxies."""

    log_level: Literal["critical", "error", "warning", "info", "debug"] = "info"
    """Uvicorn log level used by the shared HTTP server."""

    enable: Literal["unset", "true", "false"] = "unset"
    """HTTP server startup mode.

    - ``unset``: auto start only when at least one driver mounts a sub-app.
    - ``true``: always start HTTP server.
    - ``false``: never start HTTP server.
    """

    @field_validator("root_path", mode="before")
    def normalize_root_path(cls, v):
        if v is None:
            return ""
        if not isinstance(v, str):
            raise ValueError(f"Invalid http.root_path: {v}")
        rp = v.strip()
        if not rp or rp == "/":
            return ""
        if not rp.startswith("/"):
            rp = f"/{rp}"
        return rp.rstrip("/")

    @field_validator("enable", mode="before")
    def normalize_enable(cls, v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if v is None:
            return "unset"
        if not isinstance(v, str):
            raise ValueError(f"Invalid http.enable: {v}")
        val = v.strip().lower()
        if val not in {"unset", "true", "false"}:
            raise ValueError("http.enable must be one of: unset, true, false")
        return val


class AdminApiConfig(BaseModel):
    """Admin API configuration (driver status, reload, etc.)."""

    enable: CoercedBool = False
    """Enable the admin API endpoints (``/_nextbridge/drivers``, etc.).

    Disabled by default.  When enabled, ``password`` must also be set."""

    password: str = ""
    """Password for admin API access (HTTP Basic Auth, username ignored).

    Must be non-empty when ``enable`` is true."""


class ExternalDriverConfig(BaseModel):
    """Configuration for an external driver loaded from a pip package or file.

    The driver module must call ``drivers.registry.register()`` at import
    time — the same contract as built-in drivers.

    Example::

        global:
          plugins:
            drivers:
              enabled:
                - qq
                - mycustom
              external:
                mycustom:
                  module: "nextbridge_mycustom.driver"
    """

    module: str
    """Python module path to import, e.g. ``"nextbridge_mycustom.driver"``."""


class GeneralPluginEntry(BaseModel):
    """Configuration for an external general plugin loaded from a pip package or file.

    The plugin module must call ``plugins.registry.register()`` at import
    time — the same contract as built-in plugins.

    Example::

        global:
          plugins:
            general:
              enabled:
                - stats
              external:
                my_plugin:
                  module: "nextbridge_myplugin"
    """

    module: str
    """Python module path to import, e.g. ``"nextbridge_myplugin"``."""


class GeneralPluginConfig(BaseModel):
    """General (non-driver) plugin selection configuration."""

    enabled: list[str] = []
    """Plugin names to enable. Empty = no general plugins."""

    external: dict[str, GeneralPluginEntry] = {}
    """External plugin imports, keyed by plugin name."""


class DriversConfig(BaseModel):
    """Driver selection configuration.

    Controls which built-in and external drivers are loaded at startup.

    When ``enabled`` is **empty** (the default), NextBridge auto-discovers
    drivers from the config file's top-level keys (backwards-compatible).
    When ``enabled`` is **populated**, only the listed drivers are loaded.

    External drivers listed under ``external`` are imported and registered
    before any built-in driver of the same name, allowing third-party
    packages to override or extend built-in functionality.
    """

    enabled: list[str] = []
    """Driver names to load.  Empty = auto-discover from config file keys."""

    external: dict[str, ExternalDriverConfig] = {}
    """External driver imports, keyed by driver name."""


class PluginConfig(BaseModel):
    """Plugin discovery and driver lifecycle configuration."""

    paths: list[str] = []
    """Local directories to scan for driver plugin ``.py`` files."""

    drivers: DriversConfig = DriversConfig()
    """Driver selection and external driver configuration."""

    general: GeneralPluginConfig = GeneralPluginConfig()
    """General (non-driver) plugin selection configuration."""

    config: dict[str, dict] = {}
    """Per-plugin configuration, keyed by plugin name."""

    auto_restart: CoercedBool = True
    """Automatically restart crashed drivers with exponential backoff."""

    max_restart_attempts: int = 5
    """Maximum restart attempts before a crashed driver is abandoned."""

    health_check_interval: int = 60
    """Seconds between periodic driver health checks.  Set to 0 to disable."""

    admin: AdminApiConfig = AdminApiConfig()
    """Admin API configuration (driver status, reload, etc.)."""


class MiddlewareConfig(BaseModel):
    """Message middleware configuration."""

    enabled: list[str] = []
    """Middleware names to enable (evaluated in list order)."""


class GlobalConfig(BaseModel):
    """Global configuration options that apply to all drivers unless overridden."""

    command_prefix: str = "nb"
    """Prefix used for built-in bridge commands, e.g. ``/nb bind setup``.

    The value is written without the leading slash. The default is ``nb``.
    """

    proxy: str | None = UNSET
    """Global proxy URL for all drivers that support proxy configuration.
    Individual driver proxy settings will override this global setting."""

    base_url: str = ""
    """Public base URL used when generating externally reachable links.

    Example: ``https://bridge.example.com``
    """

    strict_echo_match: CoercedBool = False
    """Controls how the bridge prevents echoing messages back to the same channel/instance.

    When False (default): skips if target_id == msg.instance_id OR target_channel == msg.channel.
    When True: skips only if target_id == msg.instance_id AND target_channel == msg.channel.

    Default is False to maximize echo prevention."""

    fuzzy_mention_match: CoercedBool = False
    """Controls whether mentions without exact bind mapping should fall back to fuzzy nickname matching.

    When True: Attempts to match mentioned user's name against known display names in the target platform.
    When False (default): Only exact ID bounds or native platform mentions work.

    Default is False."""

    mention_notify_control: CoercedBool = True
    """Controls whether users can customize cross-platform @mention notification preferences.

    When True (default): Users can use ``/nb notify`` commands to choose which bound platforms
    receive @mention notifications (all / whitelist / blacklist).
    When False: All bound platforms are always notified. The ``/nb notify`` commands return a
    disabled hint.

    Default is True."""

    send_timeout: float = 2.0
    """Maximum time (seconds) a single message send may take before it is offloaded
    to the slow-send queue so it no longer blocks subsequent messages.

    Messages that exceed this timeout keep sending in the background while the
    main worker continues with the next message. Default is 2.0 seconds."""

    log: LoggingConfig = LoggingConfig()
    """Logging configuration for controlling log output and rotation."""

    database: DatabaseConfig = DatabaseConfig()
    """Database configuration for message and user mappings."""

    http: HttpConfig = HttpConfig()
    """Shared HTTP server configuration for mounted driver webhooks."""

    plugins: PluginConfig = PluginConfig()
    """Plugin discovery and driver lifecycle configuration."""

    middleware: MiddlewareConfig = MiddlewareConfig()
    """Message middleware configuration."""

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
        if v is None or v.lower() in ["disabled", "disable", "unset"]:
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

    @field_validator("base_url", mode="before")
    def normalize_base_url(cls, v):
        if v is None:
            return ""
        if not isinstance(v, str):
            raise ValueError(f"Invalid global.base_url: {v}")
        base = v.strip()
        if not base:
            return ""
        if not base.startswith(("http://", "https://")):
            base = f"https://{base.lstrip('/')}"
        return base.rstrip("/")


# ---------------------------------------------------------------------------
# Base for all driver config blocks — unknown keys are a validation error
# ---------------------------------------------------------------------------


class _DriverConfig(BaseModel):
    """Shared base for every per-driver config model.

    Sets ``extra="forbid"`` so typos in the config file are caught at startup
    rather than silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    proxy: str | None = UNSET
    """Proxy URL used by driver API/gateway requests."""

    media_proxy: str | None = UNSET
    """Proxy URL used only when fetching media/attachments.

    Defaults to following ``proxy`` when unset.
    """


# ---------------------------------------------------------------------------
# Rule validation models
# ---------------------------------------------------------------------------


class Rule(BaseModel):
    """Pydantic model for a single routing rule."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    type: Literal["connect", "forward"] | None = None
    channels: dict[str, object] | None = None
    from_: dict[str, object] | None = Field(None, alias="from")
    to: dict[str, object] | None = None
    msg: dict[str, object] | None = None


class RulesFile(BaseModel):
    """Pydantic model for the rules file (top-level container)."""

    model_config = ConfigDict(extra="allow")

    rules: list[Rule] = []
