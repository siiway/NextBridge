"""
Driver registry.

Each driver module calls ``register()`` at import time.  ``main.py`` then
auto-discovers all driver modules via ``pkgutil.iter_modules`` so no central
list needs to be maintained — drop a file into ``drivers/`` and it's live.
"""

from __future__ import annotations

from pydantic import BaseModel

_REGISTRY: dict[str, tuple[type[BaseModel], type]] = {}


def register(name: str, config_cls: type[BaseModel], driver_cls: type) -> None:
    """Register a driver under *name*.

    Args:
        name:       Platform key used in the config file  (e.g. ``"qq"``).
        config_cls: Pydantic model class for per-instance config validation.
        driver_cls: ``BaseDriver`` subclass to instantiate.
    """
    _REGISTRY[name] = (config_cls, driver_cls)


def all_drivers() -> dict[str, tuple[type[BaseModel], type]]:
    """Return a snapshot of ``{name: (config_cls, driver_cls)}`` for every
    registered driver."""
    return dict(_REGISTRY)
