from __future__ import annotations

from os import environ
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

import services.logger as log

UNSET = "unset"
logger = log.get_logger("config_schema")


def Unsettable(**kwargs: Any) -> Any:
    """标记字段支持 'unset' 哨兵值, 前端将显示一个复选框来控制是否未设置."""
    extra = dict(kwargs.pop("json_schema_extra", {}) or {})
    extra["x-nb-unset"] = True
    return Field(json_schema_extra=extra, **kwargs)


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
    """数据库连接配置, 用于 SQLAlchemy ORM."""

    url: str = "sqlite:///data.db"
    """SQLAlchemy 数据库连接 URL. 相对路径的 SQLite 会在 data 目录下解析."""

    echo: bool = False
    """启用 SQLAlchemy 查询日志, 用于调试."""

    pool_size: int | None = None
    """连接池大小. 未指定时使用 SQLAlchemy 默认值."""

    max_overflow: int | None = None
    """连接池最大溢出数. 未指定时使用 SQLAlchemy 默认值."""

    pool_recycle: int = 3600
    """连接回收时间（秒, 默认 1 小时）."""

    sslmode: str | None = None
    """PostgreSQL SSL 模式 (如 ``require``, ``prefer``, ``disable``) . 仅 PostgreSQL 有效."""

    connect_timeout: int | None = None
    """PostgreSQL 连接超时（秒）. 仅 PostgreSQL 有效."""

    application_name: str | None = None
    """PostgreSQL 应用名称, 用于连接标识. 仅 PostgreSQL 有效."""


class LoggingConfig(BaseModel):
    """日志输出与轮转配置."""

    show_source: Literal["auto", "always", "never"] = "auto"
    """控制日志中是否显示源码位置.

    - ``auto``: 仅在 DEBUG/TRACE 级别显示
    - ``always``: 始终显示
    - ``never``: 从不显示
    """

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    """控制台日志级别. 开发或排障时设为 DEBUG 可获取详细输出."""

    file_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "DEBUG"
    """文件日志级别. 默认为 DEBUG 以捕获所有日志."""

    dir: str | None = "logs"
    """日志文件目录. 设为 None 或空字符串可禁用文件日志."""

    rotation_size: str = "100 MB"
    """单个日志文件的最大大小 (如 ``"100 MB"``, ``"500 MB"``) , 超出后自动轮转."""

    retention_days: int = 7
    """日志文件保留天数. 设为 0 可禁用自动删除."""

    compression: (
        Literal["gz", "bz2", "xz", "lzma", "tar", "tar.gz", "tar.bz2", "tar.xz", "zip"]
        | None
    ) = "zip"
    """轮转日志文件的压缩格式 (如 ``"zip"``, ``"gz"``, ``"tar.gz"``) . 设为 None 可禁用压缩."""

    @field_validator("level", "file_level", mode="before")
    def normalize_level(cls, v):
        if v is None:
            return v
        if not isinstance(v, str):
            raise ValueError(f"无效的日志级别: {v}")
        upper = v.strip().upper()
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if upper not in valid:
            raise ValueError(f"无效的日志级别: {v}")
        return upper


class HttpConfig(BaseModel):
    """共享 HTTP 服务器配置, 用于挂载驱动的 Webhook."""

    host: str = "0.0.0.0"
    """HTTP 服务器监听地址."""

    port: int = 9080
    """HTTP 服务器监听端口."""

    root_path: str = ""
    """可选的 ASGI root_path, 用于反向代理路径前缀的场景."""

    log_level: Literal["critical", "error", "warning", "info", "debug"] = "info"
    """共享 HTTP 服务器的 Uvicorn 日志级别."""

    enable: Literal["unset", "true", "false"] = "unset"
    """HTTP 服务器启动模式.

    - ``unset``: 仅当有驱动挂载子应用时自动启动
    - ``true``: 始终启动
    - ``false``: 从不启动
    """

    @field_validator("root_path", mode="before")
    def normalize_root_path(cls, v):
        if v is None:
            return ""
        if not isinstance(v, str):
            raise ValueError(f"无效的 http.root_path: {v}")
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
            raise ValueError(f"无效的 http.enable: {v}")
        val = v.strip().lower()
        if val not in {"unset", "true", "false"}:
            raise ValueError("http.enable 只能是 unset / true / false 之一")
        return val


class WebuiConfig(BaseModel):
    """WebUI 管理面板配置."""

    enable: CoercedBool = True
    """是否在共享 HTTP 服务器的 ``/webui`` 路径提供 WebUI 管理面板.

    凭据单独存储在 ``data/webui.json`` 中 (不会写入此文件) .
    如不需要管理面板, 可在此禁用.
    """


class AdminApiConfig(BaseModel):
    """管理 API 配置 (驱动状态、重载等)."""

    enable: CoercedBool = False
    """启用管理 API 端点 (``/_nextbridge/drivers`` 等) .

    默认禁用. 启用时 ``password`` 也必须设置."""

    password: str = ""
    """管理 API 的访问密码 (HTTP Basic Auth, 忽略用户名) .

    当 ``enable`` 为 true 时不能为空."""


class ExternalDriverConfig(BaseModel):
    """外部驱动配置, 从 pip 包或文件加载.

    驱动模块必须在导入时调用 ``drivers.registry.register()`` —— 与内置驱动相同的契约.

    示例::

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
    """要导入的 Python 模块路径, 如 ``"nextbridge_mycustom.driver"`` ."""


class DriversConfig(BaseModel):
    """驱动选择配置.

    控制在启动时加载哪些内置和外部驱动.

    当 ``enabled`` 为 **空** (默认) 时, NextBridge 从配置文件顶层键自动发现驱动。
    当 ``enabled`` 为非空时, 仅加载列表中的驱动。

    在 ``external`` 中列出的外部驱动会在同名内置驱动之前导入并注册,
    允许第三方包覆盖或扩展内置功能。
    """

    enabled: list[str] = []
    """要加载的驱动名称列表. 空列表表示从配置文件键自动发现."""

    external: dict[str, ExternalDriverConfig] = {}
    """外部驱动导入配置, 按驱动名称键值."""


class PluginConfig(BaseModel):
    """插件发现与驱动生命周期配置."""

    paths: list[str] = []
    """本地目录, 用于扫描驱动插件 ``.py`` 文件."""

    drivers: DriversConfig = DriversConfig()
    """驱动选择与外部驱动配置."""

    auto_restart: CoercedBool = True
    """崩溃后自动重启驱动, 附带指数退避."""

    max_restart_attempts: int = 5
    """放弃前的最大重启尝试次数."""

    health_check_interval: int = 60
    """健康检查间隔（秒）. 设为 0 可禁用."""

    admin: AdminApiConfig = AdminApiConfig()
    """管理 API 配置 (驱动状态、重载等)."""


class MiddlewareConfig(BaseModel):
    """消息中间件配置."""

    enabled: list[str] = []
    """要启用的中间件名称 (按列表顺序执行)."""


class GlobalConfig(BaseModel):
    """全局配置, 适用于所有驱动 (除非被覆盖)."""

    command_prefix: str = "nb"
    """内置桥接命令前缀, 如 ``/nb bind setup``.

    值不包含前导斜杠. 默认为 ``nb`` .
    """

    proxy: str | None = Unsettable(default=UNSET)
    """全局代理 URL, 适用于所有支持代理的驱动.
    单个驱动的代理设置会覆盖此全局设置."""

    base_url: str = ""
    """生成外部可访问链接时使用的公网基础 URL.

    示例: ``https://bridge.example.com``
    """

    strict_echo_match: CoercedBool = False
    """控制桥接避免消息回显到同一频道/实例的方式.

    为 False (默认) : 当 target_id == msg.instance_id 或 target_channel == msg.channel 时跳过.
    为 True: 仅当 target_id == msg.instance_id 且 target_channel == msg.channel 时跳过.

    默认 False 以最大程度防止回显."""

    fuzzy_mention_match: CoercedBool = False
    """控制无精确绑定的 @ 提及是否回退到模糊昵称匹配.

    为 True: 尝试将提及的用户名与目标平台的已知显示名称进行匹配.
    为 False (默认) : 仅精确 ID 绑定或原生平台 @ 有效.

    默认 False."""

    log: LoggingConfig = LoggingConfig()
    """日志输出与轮转配置."""

    database: DatabaseConfig = DatabaseConfig()
    """数据库连接配置."""

    http: HttpConfig = HttpConfig()
    """共享 HTTP 服务器配置."""

    webui: WebuiConfig = WebuiConfig()
    """WebUI 管理面板配置."""

    plugins: PluginConfig = PluginConfig()
    """插件发现与驱动生命周期配置."""

    middleware: MiddlewareConfig = MiddlewareConfig()
    """消息中间件配置."""

    @field_validator("command_prefix", mode="before")
    def normalize_command_prefix(cls, v):
        if v is None:
            return "nb"
        if not isinstance(v, str):
            raise ValueError(f"无效的命令前缀: {v}")
        prefix = v.strip().lstrip("/")
        if not prefix:
            raise ValueError("命令前缀不能为空")
        return prefix

    @field_validator("proxy", mode="after")
    def get_proxy_from_env(cls, v: str):
        if v.lower() in ["disabled", "disable", "unset"]:
            logger.debug("全局代理已手动禁用")
            return None

        elif v:
            logger.debug(f"使用配置文件中的全局代理: {v}")
            return v or None

        for env_var in ["http_proxy", "https_proxy", "all_proxy"]:
            env_value = environ.get(env_var) or environ.get(env_var.upper())
            if env_value:
                logger.debug(f"使用环境变量 {env_var} 中的全局代理: {env_value}")
                return env_value or None

        logger.debug("未找到任何全局代理配置")
        return None

    @field_validator("base_url", mode="before")
    def normalize_base_url(cls, v):
        if v is None:
            return ""
        if not isinstance(v, str):
            raise ValueError(f"无效的 global.base_url: {v}")
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
    """所有驱动配置模型的共享基类.

    设置 ``extra="forbid"`` 以捕获配置文件中的拼写错误, 而非静默忽略.
    """

    model_config = ConfigDict(extra="forbid")

    proxy: str | None = Unsettable(default=UNSET)
    """驱动 API / 网关请求使用的代理 URL."""

    media_proxy: str | None = Unsettable(default=UNSET)
    """仅用于获取媒体/附件时的代理 URL.

    未设置时默认跟随 ``proxy`` .
    """


# ---------------------------------------------------------------------------
# Rule validation models
# ---------------------------------------------------------------------------


class Rule(BaseModel):
    """单条路由规则的 Pydantic 模型."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    type: Literal["connect", "forward"] | None = None
    channels: dict[str, object] | None = None
    from_: dict[str, object] | None = Field(None, alias="from")
    to: dict[str, object] | None = None
    msg: dict[str, object] | None = None


class RulesFile(BaseModel):
    """规则文件的 Pydantic 模型 (顶层容器)."""

    model_config = ConfigDict(extra="allow")

    rules: list[Rule] = []
