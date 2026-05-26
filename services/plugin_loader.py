"""Plugin discovery and loading.

Sources (checked in order, later overrides earlier):
  1. Built-in:      ``drivers/<platform>.py``
  2. Entry points:  pip packages advertising ``nextbridge.drivers``
  3. Local paths:   directories listed in ``global.plugins.paths``
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import services.logger as log

logger = log.get_logger("plugin_loader")

ENTRYPOINT_GROUP = "nextbridge.drivers"


@dataclass
class PluginInfo:
    name: str
    source: str  # "builtin" | "entrypoint" | "local"
    module_path: str
    package_name: str = ""
    package_version: str = ""


def discover_entrypoint_drivers() -> dict[str, PluginInfo]:
    """Scan installed packages for ``nextbridge.drivers`` entry points.

    A pip package advertises a driver via ``pyproject.toml``::

        [project.entry-points."nextbridge.drivers"]
        myplatform = "nextbridge_myplatform.driver"

    The target module must call ``drivers.registry.register()`` at import
    time (same contract as built-in drivers).
    """
    found: dict[str, PluginInfo] = {}
    try:
        eps = importlib.metadata.entry_points(group=ENTRYPOINT_GROUP)
    except Exception:
        return found

    for ep in eps:
        dist = getattr(ep, "dist", None)
        found[ep.name] = PluginInfo(
            name=ep.name,
            source="entrypoint",
            module_path=ep.value,
            package_name=dist.name if dist else "",
            package_version=dist.version if dist else "",
        )
    return found


def discover_local_drivers(paths: list[str]) -> dict[str, PluginInfo]:
    """Scan local directories for ``.py`` driver modules."""
    found: dict[str, PluginInfo] = {}
    for dir_str in paths:
        directory = Path(dir_str).resolve()
        if not directory.is_dir():
            logger.warning(f"Plugin path not found: {directory}")
            continue
        for py_file in sorted(directory.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            name = py_file.stem
            found[name] = PluginInfo(
                name=name,
                source="local",
                module_path=str(py_file),
            )
    return found


def _load_module(info: PluginInfo) -> None:
    if info.source == "builtin":
        module_name = f"drivers.{info.name}"
        if importlib.util.find_spec(module_name) is None:
            logger.warning(f"Built-in driver module '{info.name}' not found, skipping.")
            return
        importlib.import_module(module_name)

    elif info.source == "entrypoint":
        importlib.import_module(info.module_path)

    elif info.source == "local":
        path = Path(info.module_path)
        module_name = f"_nextbridge_plugin_{info.name}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.error(f"Cannot load plugin from {path}")
            return
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        logger.info(f"Loaded local plugin: {info.name} from {path}")


def load_all_drivers(
    enabled_platforms: list[str],
    plugin_paths: list[str] | None = None,
) -> dict[str, PluginInfo]:
    """Discover and import all driver modules.

    Returns a mapping of platform name to :class:`PluginInfo` for every
    driver that was actually loaded.
    """
    all_plugins: dict[str, PluginInfo] = {}

    for platform in enabled_platforms:
        all_plugins[platform] = PluginInfo(
            name=platform, source="builtin", module_path=f"drivers.{platform}"
        )

    ep_plugins = discover_entrypoint_drivers()
    for name, info in ep_plugins.items():
        if name in enabled_platforms:
            all_plugins[name] = info
            logger.info(
                f"Entry-point driver: {name} "
                f"({info.package_name} {info.package_version})"
            )

    if plugin_paths:
        local_plugins = discover_local_drivers(plugin_paths)
        for name, info in local_plugins.items():
            if name in enabled_platforms:
                all_plugins[name] = info
                logger.info(f"Local driver: {name} from {info.module_path}")

    loaded: dict[str, PluginInfo] = {}
    for name, info in all_plugins.items():
        try:
            _load_module(info)
            loaded[name] = info
        except Exception:
            logger.opt(exception=True).error(f"Failed to load driver: {name}")

    return loaded
