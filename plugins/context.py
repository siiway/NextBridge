from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

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
        self._commands: list[str] = []
        self._events: list[tuple[str, Callable]] = []
        self._middleware_names: list[str] = []

    @property
    def bridge(self):
        return self._bridge

    @property
    def http_server(self):
        return self._http_server

    @property
    def event_bus(self):
        return self._event_bus

    @property
    def middleware(self):
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

    def register_command(self, name: str, handler: Callable) -> None:
        """Register a ``/<prefix> <name>`` command and track it for cleanup."""
        self._bridge.register_command(name, handler)
        self._commands.append(name)

    def on_event(self, event: str, handler: Callable) -> None:
        """Subscribe to an EventBus event and track it for cleanup."""
        if self._event_bus is not None:
            self._event_bus.on(event, handler)
        self._events.append((event, handler))

    def add_receive_middleware(
        self, name: str, handler: Callable, priority: int = 100
    ) -> None:
        """Add a receive middleware and track it for cleanup."""
        if self._middleware is not None:
            self._middleware.add_receive(name, handler, priority)
        self._middleware_names.append(name)

    def add_send_middleware(
        self, name: str, handler: Callable, priority: int = 100
    ) -> None:
        """Add a send middleware and track it for cleanup."""
        if self._middleware is not None:
            self._middleware.add_send(name, handler, priority)
        self._middleware_names.append(name)

    def cleanup(self) -> None:
        """Undo every tracked registration; safe to call repeatedly."""
        for name in list(self._commands):
            if self._bridge._commands.get(name) in (None,):
                continue
            # Only unregister if the command points to a handler we registered
            # or if it was registered through this context. To prevent unregistering
            # replacement instances during restart, we track handlers.
            self._bridge.unregister_command(name)
        for event, handler in list(self._events):
            if self._event_bus is not None:
                self._event_bus.off(event, handler)
        for name in list(self._middleware_names):
            if self._middleware is not None:
                self._middleware.remove(name)
        self._commands.clear()
        self._events.clear()
        self._middleware_names.clear()

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
