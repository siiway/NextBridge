from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import loguru
import uvicorn
from fastapi import FastAPI

import services.logger as log
from services.admin_api import build_admin_app

if TYPE_CHECKING:
    from plugins.manager import PluginManager
    from services.bridge import Bridge
    from services.driver_manager import DriverManager
    from services.metrics import MetricsCollector
    from services.reload import ReloadEngine

logger = log.get_logger("http")


class _UvicornLogHandler(logging.Handler):
    """Forward stdlib uvicorn logs to project logger with unified format."""

    def __init__(self):
        super().__init__()
        self.bound_logger = loguru.logger.bind(_uvicorn=True)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            level = record.levelname.upper()
            if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
                level = "INFO"
            self.bound_logger.log(level, msg)
        except Exception:
            return


def _configure_uvicorn_logging(level: str) -> None:
    normalized = (level or "info").upper()
    if normalized == "WARN":
        normalized = "WARNING"

    handler = _UvicornLogHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = False
        uv_logger.setLevel(normalized)
        uv_logger.addHandler(handler)


@dataclass(slots=True)
class HttpMount:
    instance_id: str
    path: str
    app: FastAPI


class HttpServerManager:
    """Hosts a shared FastAPI app and mounts driver sub-apps under paths."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9080,
        root_path: str = "",
        log_level: str = "info",
        start_without_mounts: bool = False,
        version: str = "UNKNOWN",
    ):
        self.host = host
        self.port = port
        self.root_path = root_path
        self.log_level = log_level.lower()
        self.start_without_mounts = start_without_mounts
        self.version = version

        self._root_app: FastAPI = FastAPI()
        self._server: uvicorn.Server | None = None
        self._mounts: list[HttpMount] = []
        self._mounted_paths: set[str] = set()
        self._ready = asyncio.Event()
        self._started = False
        self._driver_manager: DriverManager | None = None
        self._plugin_manager: PluginManager | None = None
        self._reload_engine: ReloadEngine | None = None
        self._metrics: MetricsCollector | None = None
        self._bridge: Bridge | None = None
        self._admin_enabled: bool = False
        self._admin_user: str = ""
        self._admin_password: str = ""

    @staticmethod
    def _normalize_path(path: str) -> str:
        path = (path or "/").strip()
        if not path.startswith("/"):
            path = f"/{path}"
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        return path

    def mount(self, instance_id: str, path: str, app: Any) -> None:
        """Register an ASGI sub-app for a driver.

        Can be called before or after the HTTP server starts.
        If instance_id is already mounted, it is cleanly unmounted first.
        """
        normalized = self._normalize_path(path)

        # If this instance_id already has a mount, unmount it first
        self.unmount(instance_id)

        if normalized in self._mounted_paths:
            raise ValueError(f"Duplicate HTTP mount path: {normalized}")

        self._mounted_paths.add(normalized)
        mount_entry = HttpMount(instance_id=instance_id, path=normalized, app=app)
        self._mounts.append(mount_entry)
        self._root_app.mount(normalized, app)
        logger.debug(f"HTTP mount registered: {instance_id} -> {normalized}")

        self._ready.set()

    def unmount(self, instance_id: str) -> None:
        """Unmount any ASGI sub-apps registered for *instance_id*."""
        to_remove = [m for m in self._mounts if m.instance_id == instance_id]
        if not to_remove:
            return
        for m in to_remove:
            self._mounts.remove(m)
            self._mounted_paths.discard(m.path)
            self._remove_route_by_path(m.path)
            logger.debug(f"HTTP unmounted: {instance_id} -> {m.path}")

    def _remove_route_by_path(self, path: str) -> None:
        routes = getattr(self._root_app.router, "routes", None)
        if routes is not None:
            self._root_app.router.routes = [
                r for r in routes if getattr(r, "path", None) != path
            ]

    def set_driver_manager(self, manager: DriverManager) -> None:
        self._driver_manager = manager

    def set_plugin_manager(self, manager: PluginManager) -> None:
        self._plugin_manager = manager

    def set_reload_engine(self, engine: ReloadEngine) -> None:
        self._reload_engine = engine

    def set_metrics(self, metrics: MetricsCollector) -> None:
        self._metrics = metrics

    def set_bridge(self, bridge: Bridge) -> None:
        self._bridge = bridge

    def configure_admin(
        self, *, enabled: bool, user: str = "", password: str = ""
    ) -> None:
        self._admin_enabled = enabled
        self._admin_user = user
        self._admin_password = password

    def has_mounts(self) -> bool:
        return bool(self._mounts)

    def should_start(self) -> bool:
        return self.start_without_mounts or self.has_mounts()

    async def run(self) -> None:
        """Start shared uvicorn server if mount exists or start_without_mounts is enabled."""
        if not self.start_without_mounts:
            await self._ready.wait()

        if not self.should_start():
            return

        if not any(
            getattr(r, "path", None) == "/_nextbridge"
            for r in getattr(self._root_app.router, "routes", [])
        ):
            admin_app = build_admin_app(
                version=self.version,
                debug=self.log_level == "debug",
                bridge=self._bridge,
                driver_manager=self._driver_manager,
                plugin_manager=self._plugin_manager,
                reload_engine=self._reload_engine,
                metrics=self._metrics,
                admin_enabled=self._admin_enabled,
                admin_user=self._admin_user,
                admin_password=self._admin_password,
            )
            self._root_app.mount("/_nextbridge", admin_app)

        host = f"[{self.host}]" if ":" in self.host else self.host
        root_path = self.root_path if not self.root_path == "/" else ""
        logger.info(f"Shared HTTP server starting on {host}:{self.port}{root_path}")
        logger.debug(
            f"(root_path='{self.root_path or '/'}', mounts={len(self._mounts)}, "
            f"start_without_mounts={self.start_without_mounts})"
        )

        _configure_uvicorn_logging(self.log_level)

        cfg = uvicorn.Config(
            app=self._root_app,
            host=self.host,
            port=self.port,
            log_level=self.log_level,
            root_path=self.root_path,
            access_log=False,
            log_config=None,
        )
        server = uvicorn.Server(cfg)
        self._server = server
        self._started = True
        await server.serve()

    async def stop(self) -> None:
        """Gracefully stop the running uvicorn server."""
        if self._server is not None:
            self._server.should_exit = True
