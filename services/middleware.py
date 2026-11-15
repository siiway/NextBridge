from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import services.logger as log
from services.message import NormalizedMessage

logger = log.get_logger("middleware")

ReceiveMiddleware = Callable[
    [NormalizedMessage],
    Awaitable[NormalizedMessage | None],
]

SendMiddleware = Callable[
    [str, dict, str, dict],  # target_id, channel, text, kwargs
    Awaitable[tuple[str, dict] | None],
]


@dataclass(order=True)
class _MiddlewareEntry:
    priority: int
    name: str
    handler: Any = field(compare=False)


class MiddlewareChain:
    """Pre-receive and pre-send message middleware.

    Two chains, each ordered by priority (lower = earlier).

    **Receive** — applied when a driver calls ``bridge.on_message()``::

        async def handler(msg) -> NormalizedMessage | None
        # Return None to drop the message.

    **Send** — applied before bridge dispatches to each sender::

        async def handler(target_id, channel, text, kwargs) -> tuple[str, dict] | None
        # Return None to suppress the send.
    """

    def __init__(self) -> None:
        self._receive: list[_MiddlewareEntry] = []
        self._send: list[_MiddlewareEntry] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def add_receive(
        self, name: str, handler: ReceiveMiddleware, priority: int = 100
    ) -> None:
        self._receive.append(_MiddlewareEntry(priority, name, handler))
        self._receive.sort()
        logger.debug(f"Registered receive middleware: {name} (priority={priority})")

    def add_send(self, name: str, handler: SendMiddleware, priority: int = 100) -> None:
        self._send.append(_MiddlewareEntry(priority, name, handler))
        self._send.sort()
        logger.debug(f"Registered send middleware: {name} (priority={priority})")

    def remove(self, name: str) -> None:
        self._receive = [e for e in self._receive if e.name != name]
        self._send = [e for e in self._send if e.name != name]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def run_receive(self, msg: NormalizedMessage) -> NormalizedMessage | None:
        current = msg
        for entry in self._receive:
            try:
                result = await entry.handler(current)
                if result is None:
                    logger.debug(f"Message dropped by middleware '{entry.name}'")
                    return None
                current = result
            except Exception:
                logger.opt(exception=True).warning(
                    f"Receive middleware '{entry.name}' failed, continuing"
                )
        return current

    async def run_send(
        self, target_id: str, channel: dict, text: str, kwargs: dict
    ) -> tuple[str, dict] | None:
        current_text = text
        current_kwargs = kwargs
        for entry in self._send:
            try:
                result = await entry.handler(
                    target_id, channel, current_text, current_kwargs
                )
                if result is None:
                    logger.debug(
                        f"Send to '{target_id}' suppressed by middleware '{entry.name}'"
                    )
                    return None
                current_text, current_kwargs = result
            except Exception:
                logger.opt(exception=True).warning(
                    f"Send middleware '{entry.name}' failed, continuing"
                )
        return current_text, current_kwargs

    @property
    def has_receive(self) -> bool:
        return bool(self._receive)

    @property
    def has_send(self) -> bool:
        return bool(self._send)
