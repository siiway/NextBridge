from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import services.logger as log

if TYPE_CHECKING:
    from services.config_schema import GeneralPluginEntry

logger = log.get_logger("plugin_loader")

ENTRYPOINT_GROUP = "nextbridge.plugins"


@dataclass
class PluginInfo:
    name: str
    source: str
    module_path: str
    package_name: str = ""
    package_version: str = ""


def discover_entrypoint_plugins() -> dict[str, PluginInfo]:
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


def discover_local_plugins(paths: list[str]) -> dict[str, PluginInfo]:
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


def discover_builtin_plugins() -> dict[str, PluginInfo]:
    found: dict[str, PluginInfo] = {}
    plugins_dir = Path(__file__).resolve().parent
    for py_file in sorted(plugins_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        name = py_file.stem
        found[name] = PluginInfo(
            name=name,
            source="builtin",
            module_path=f"plugins.{name}",
        )
    return found


def _load_module(info: PluginInfo) -> None:
    if info.source == "builtin":
        if importlib.util.find_spec(info.module_path) is None:
            logger.warning(f"Built-in plugin module '{info.name}' not found, skipping.")
            return
        importlib.import_module(info.module_path)

    elif info.source in ("entrypoint", "external"):
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


def load_plugins(
    enabled: list[str],
    external: dict[str, GeneralPluginEntry],
    paths: list[str] | None,
) -> dict[str, PluginInfo]:
    from services.config_schema import GeneralPluginEntry

    if external is None:
        external = {}

    all_plugins: dict[str, PluginInfo] = {}

    for name in enabled:
        all_plugins[name] = PluginInfo(
            name=name, source="builtin", module_path=f"plugins.{name}"
        )

    for name, ext_cfg in list(external.items()):
        if isinstance(ext_cfg, dict):
            ext_cfg = GeneralPluginEntry(**ext_cfg)
        all_plugins[name] = PluginInfo(
            name=name, source="external", module_path=ext_cfg.module
        )

    ep_plugins = discover_entrypoint_plugins()
    for name, info in ep_plugins.items():
        if name in enabled and name not in external:
            all_plugins[name] = info
            logger.info(
                f"Entry-point plugin: {name} "
                f"({info.package_name} {info.package_version})"
            )

    if paths:
        local_plugins = discover_local_plugins(paths)
        for name, info in local_plugins.items():
            if name in enabled and name not in external:
                all_plugins[name] = info
                logger.info(f"Local plugin: {name} from {info.module_path}")

    loaded: dict[str, PluginInfo] = {}
    for name, info in all_plugins.items():
        try:
            _load_module(info)
            loaded[name] = info
        except Exception:
            logger.opt(exception=True).error(f"Failed to load plugin: {name}")

    return loaded
