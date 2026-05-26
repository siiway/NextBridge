from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from pydantic import BaseModel

import services.logger as log
from services.config import UNSET, get_proxy

if TYPE_CHECKING:
    from services.bridge import Bridge
    from services.driver_context import DriverContext

T = TypeVar("T", bound=BaseModel)

DRIVER_API_VERSION = 2


# ------------------------------------------------------------------
# Capability & metadata declarations
# ------------------------------------------------------------------


class DriverCapability(Enum):
    SEND = auto()
    RECEIVE = auto()
    WEBHOOK = auto()
    ATTACHMENTS = auto()
    MENTIONS = auto()
    REPLIES = auto()


@dataclass
class DriverMeta:
    platform: str = ""
    display_name: str = ""
    version: str = "0.0.0"
    api_version: int = DRIVER_API_VERSION
    capabilities: set[DriverCapability] = field(
        default_factory=lambda: {DriverCapability.SEND, DriverCapability.RECEIVE}
    )
    author: str = ""
    url: str = ""


class DriverHealth(Enum):
    UNKNOWN = "unknown"
    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    STOPPED = "stopped"


# ------------------------------------------------------------------
# Base driver
# ------------------------------------------------------------------


class BaseDriver(ABC, Generic[T]):
    """Abstract base class for all platform drivers.

    The third constructor parameter accepts either a legacy ``Bridge``
    instance (API v1) or a ``DriverContext`` (API v2).  Existing drivers
    that pass ``bridge`` continue to work unchanged.
    """

    meta: DriverMeta = DriverMeta()

    def __init__(
        self,
        instance_id: str,
        config: T,
        ctx_or_bridge: DriverContext | Bridge | Any,
    ) -> None:
        self.instance_id = instance_id
        self.config: T = config

        from services.driver_context import DriverContext

        if isinstance(ctx_or_bridge, DriverContext):
            self._ctx = ctx_or_bridge
            self.bridge = ctx_or_bridge.bridge
        else:
            self._ctx = DriverContext(bridge=ctx_or_bridge)
            self.bridge = ctx_or_bridge

        self.http_server = None
        self.logger = log.get_logger(f"[{instance_id}]", instance=True)

        base_proxy = get_proxy(getattr(config, "proxy", UNSET))
        self._media_proxy = get_proxy(getattr(config, "media_proxy", UNSET), base_proxy)

        self._health = DriverHealth.UNKNOWN

    # ------------------------------------------------------------------
    # Proxy helpers
    # ------------------------------------------------------------------

    def _source_proxy_from_kwargs(self, kwargs: dict) -> str | None:
        if "source_proxy" in kwargs:
            return kwargs.get("source_proxy")
        return self._media_proxy

    def attach_http_server(self, http_server) -> None:
        self.http_server = http_server

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def start(self):
        """Start the driver (connect, authenticate, begin listening).
        Long-running drivers should loop indefinitely here."""

    async def stop(self):
        """Graceful shutdown.  Override in drivers that hold resources."""

    @abstractmethod
    async def send(self, channel: dict, text: str, **kwargs) -> str | list[str] | None:
        """Send *text* to the given *channel* on this platform."""

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> DriverHealth:
        return self._health

    @property
    def health(self) -> DriverHealth:
        return self._health

    @health.setter
    def health(self, value: DriverHealth) -> None:
        old = self._health
        self._health = value
        if old != value:
            try:
                self._ctx.emit("health_changed", driver=self, old=old, new=value)
            except Exception:
                pass
