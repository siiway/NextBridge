from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

import services.logger as log

logger = log.get_logger()


class _UvicornLogHandler(logging.Handler):
    """Forward stdlib uvicorn logs to project logger with unified format."""

    def __init__(self):
        super().__init__()
        self.bound_logger = logger.bind(name="uvicorn")

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

        self._mounts: list[HttpMount] = []
        self._mounted_paths: set[str] = set()
        self._ready = asyncio.Event()
        self._started = False

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

        Must be called before the HTTP server starts.
        """
        if self._started:
            raise RuntimeError("HTTP server already started; cannot mount new apps")

        normalized = self._normalize_path(path)
        if normalized in self._mounted_paths:
            raise ValueError(f"Duplicate HTTP mount path: {normalized}")

        self._mounted_paths.add(normalized)
        self._mounts.append(
            HttpMount(instance_id=instance_id, path=normalized, app=app)
        )
        self._ready.set()

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

        root = FastAPI()

        @root.get("/_nextbridge/health")
        async def _health() -> JSONResponse:
            payload: dict[str, object] = {
                "status": "ok",
                "version": self.version,
            }
            if self.log_level == "debug":
                payload["mounts"] = [m.path for m in self._mounts]
            return JSONResponse(payload)

        for mount in self._mounts:
            root.mount(mount.path, mount.app)
            logger.info(f"HTTP mount registered: {mount.instance_id} -> {mount.path}")

        host = f"[{self.host}]" if ":" in self.host else self.host
        root_path = self.root_path if not self.root_path == "/" else ""
        logger.info(f"Shared HTTP server starting on {host}:{self.port}{root_path}")
        logger.debug(
            f"(root_path='{self.root_path or '/'}', mounts={len(self._mounts)}, "
            f"start_without_mounts={self.start_without_mounts})"
        )

        _configure_uvicorn_logging(self.log_level)

        cfg = uvicorn.Config(
            app=root,
            host=self.host,
            port=self.port,
            log_level=self.log_level,
            root_path=self.root_path,
            access_log=False,
            log_config=None,
        )
        server = uvicorn.Server(cfg)
        self._started = True
        await server.serve()
