from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plugins import BasePlugin

_REGISTRY: dict[str, type[BasePlugin]] = {}


def register(name: str, plugin_cls: type[BasePlugin]) -> None:
    _REGISTRY[name] = plugin_cls


def unregister(name: str) -> bool:
    return _REGISTRY.pop(name, None) is not None


def all_plugins() -> dict[str, type[BasePlugin]]:
    return dict(_REGISTRY)


def get_plugin(name: str) -> type[BasePlugin] | None:
    return _REGISTRY.get(name)
