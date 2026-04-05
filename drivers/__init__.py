from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generic, TypeVar

from pydantic import BaseModel
from services.config import UNSET, get_proxy

if TYPE_CHECKING:
    from services.bridge import Bridge

T = TypeVar("T", bound=BaseModel)


class BaseDriver(ABC, Generic[T]):
    """Abstract base class for all platform drivers."""

    def __init__(self, instance_id: str, config: T, bridge: "Bridge"):
        self.instance_id = instance_id
        self.config: T = config
        self.bridge = bridge
        self.http_server = None

        # Media download proxy used by downstream attachment fetching.
        # Default follows driver-level proxy, but can be overridden by
        # per-driver media_proxy.
        base_proxy = get_proxy(getattr(config, "proxy", UNSET))
        self._media_proxy = get_proxy(getattr(config, "media_proxy", UNSET), base_proxy)

    def _source_proxy_from_kwargs(self, kwargs: dict) -> str | None:
        # Keep explicit None from kwargs (disable proxy for this send call).
        if "source_proxy" in kwargs:
            return kwargs.get("source_proxy")
        return self._media_proxy

    def attach_http_server(self, http_server) -> None:
        self.http_server = http_server

    @abstractmethod
    async def start(self):
        """Start the driver (connect, authenticate, begin listening).
        Long-running drivers should loop indefinitely here."""

    @abstractmethod
    async def send(self, channel: dict, text: str, **kwargs) -> str | None:
        """Send *text* to the given *channel* on this platform."""
