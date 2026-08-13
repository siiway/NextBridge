"""Driver registry.

Each driver module calls ``register()`` at import time.  The plugin
loader auto-discovers driver modules so no central list needs to be
maintained — drop a file into ``drivers/`` and it's live.
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel

_REGISTRY: dict[str, tuple[type[BaseModel], type]] = {}
_META: dict[str, dict[str, Any]] = {}

_CLI_HOOKS: list[Callable[..., Any]] = []


def register(
    name: str,
    config_cls: type[BaseModel],
    driver_cls: type,
    *,
    display_name: str = "",
    icon: str = "",
    channel_fields: list[dict[str, str]] | None = None,
) -> None:
    """Register a driver under *name*.

    Args:
        name:       Platform key used in the config file  (e.g. ``"qq"``).
        config_cls: Pydantic model class for per-instance config validation.
        driver_cls: ``BaseDriver`` subclass to instantiate.
        display_name: Human-readable platform name (e.g. ``"QQ"``, ``"Telegram"``).
        icon:       Icon identifier for the frontend.
        channel_fields: List of supported channel field definitions, each
            with ``{"key": ..., "label": ...}``.
    """
    _REGISTRY[name] = (config_cls, driver_cls)
    _META[name] = {
        "display_name": display_name or name,
        "icon": icon or "",
        "channel_fields": channel_fields or [],
    }


def unregister(name: str) -> bool:
    """Remove a driver from the registry.  Returns ``True`` if it existed."""
    _REGISTRY.pop(name, None)
    return _META.pop(name, None) is not None


def all_drivers() -> dict[str, tuple[type[BaseModel], type]]:
    """Return a snapshot of ``{name: (config_cls, driver_cls)}`` for every
    registered driver."""
    return dict(_REGISTRY)


def get_driver(name: str) -> tuple[type[BaseModel], type] | None:
    """Look up a single driver by platform name."""
    return _REGISTRY.get(name)


def get_meta(name: str) -> dict[str, Any]:
    """Return metadata for a driver by name, or empty dict if not found."""
    return _META.get(name, {})


def all_meta() -> dict[str, dict[str, Any]]:
    """Return a snapshot of ``{name: meta_dict}`` for every registered driver."""
    return dict(_META)


def register_cli(hook: Callable[..., Any]) -> None:
    """Register a CLI subcommand hook.

    The hook is called with an ``argparse._SubParsersAction`` and should
    add whatever subcommands the driver needs.  Called at import time,
    same pattern as ``register()``.

    Example::

        def _setup_cli(subparsers):
            p = subparsers.add_parser("mydriver", help="...")
            sub = p.add_subparsers(dest="mydriver_command")
            sub.add_parser("pair", help="Pair with remote")

        register_cli(_setup_cli)
    """
    _CLI_HOOKS.append(hook)


def all_cli_hooks() -> list[Callable[..., Any]]:
    """Return all registered CLI hooks."""
    return list(_CLI_HOOKS)
