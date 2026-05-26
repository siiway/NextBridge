from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable

import services.logger as log

logger = log.get_logger("event_bus")

EventHandler = Callable[..., Awaitable[None]]


class EventBus:
    """Lightweight async pub/sub for driver lifecycle events.

    Handlers are async callables. Errors are logged, never propagated to
    the emitter.

    Standard events::

        driver.starting   (instance_id)
        driver.started    (instance_id)
        driver.crashed    (instance_id, error)
        driver.stopped    (instance_id)
        driver.abandoned  (instance_id)
        health_changed    (driver, old, new)
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def on(self, event: str, handler: EventHandler) -> None:
        self._handlers[event].append(handler)

    def off(self, event: str, handler: EventHandler) -> None:
        handlers = self._handlers.get(event, [])
        if handler in handlers:
            handlers.remove(handler)

    def emit(self, event: str, **kwargs: Any) -> None:
        """Fire-and-forget: schedule handler tasks on the running loop."""
        for handler in self._handlers.get(event, []):
            asyncio.ensure_future(self._safe_call(event, handler, kwargs))

    async def emit_await(self, event: str, **kwargs: Any) -> None:
        """Emit and wait for all handlers to complete."""
        tasks = [
            self._safe_call(event, h, kwargs) for h in self._handlers.get(event, [])
        ]
        if tasks:
            await asyncio.gather(*tasks)

    @staticmethod
    async def _safe_call(
        event: str, handler: EventHandler, kwargs: dict[str, Any]
    ) -> None:
        try:
            await handler(**kwargs)
        except Exception:
            logger.opt(exception=True).warning(f"Event handler error for '{event}'")
