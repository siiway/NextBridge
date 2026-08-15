from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.bridge import Bridge
    from services.event_bus import EventBus
    from services.http_server import HttpServerManager
    from services.middleware import MiddlewareChain


class PluginContext:
    def __init__(
        self,
        *,
        bridge: Bridge,
        http_server: HttpServerManager | None = None,
        event_bus: EventBus | None = None,
        middleware: MiddlewareChain | None = None,
        config: dict[str, Any] | None = None,
        version: str = "",
        config_path: Path | None = None,
    ) -> None:
        self._bridge = bridge
        self._http_server = http_server
        self._event_bus = event_bus
        self._middleware = middleware
        self._config = config or {}
        self._version = version
        self._config_path = config_path

    @property
    def bridge(self):
        return self._bridge

    @property
    def http_server(self):
        return self._http_server

    @property
    def event_bus(self):
        if self._event_bus is None:
            from services.event_bus import EventBus

            self._event_bus = EventBus()
        return self._event_bus

    @property
    def middleware(self):
        if self._middleware is None:
            from services.middleware import MiddlewareChain

            self._middleware = MiddlewareChain()
        return self._middleware

    @property
    def config(self) -> dict[str, Any]:
        return self._config

    @property
    def version(self) -> str:
        return self._version

    @property
    def config_path(self) -> Path | None:
        return self._config_path

    @property
    def data_path(self) -> str:
        import services.util as util

        return util.get_data_path()

    @staticmethod
    def db():
        from services.db import msg_db

        return msg_db()

    @staticmethod
    def media():
        from services import media

        return media

    @staticmethod
    def logger(name: str = "", instance: bool = False):
        import services.logger as log_mod

        return log_mod.get_logger(name, instance)
