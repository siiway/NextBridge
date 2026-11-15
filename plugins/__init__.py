from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from enum import Enum, auto


class PluginState(Enum):
    CREATED = auto()
    LOADED = auto()
    ENABLED = auto()
    DISABLED = auto()
    UNLOADED = auto()
    ERROR = auto()


@dataclass
class PluginMeta:
    name: str
    version: str = "0.0.0"
    display_name: str = ""
    description: str = ""
    author: str = ""
    dependencies: list[str] = field(default_factory=list)


class BasePlugin(ABC):
    meta: PluginMeta = PluginMeta(name="")

    async def on_load(self, ctx) -> None:
        pass

    async def on_enable(self) -> None:
        pass

    async def on_disable(self) -> None:
        pass

    async def on_unload(self) -> None:
        pass
