from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

import services.logger as log
from plugins import BasePlugin, PluginState
from plugins.registry import all_plugins as get_registered_plugins

if TYPE_CHECKING:
    from plugins.context import PluginContext
    from plugins.loader import PluginInfo
    from services.event_bus import EventBus

logger = log.get_logger("plugin_manager")


@dataclass
class ManagedPlugin:
    info: PluginInfo | None = None
    instance: BasePlugin | None = None
    state: PluginState = PluginState.CREATED
    error: Exception | None = None
    config: dict[str, Any] = field(default_factory=dict)


class PluginManager:
    def __init__(
        self,
        event_bus: EventBus,
        ctx_factory: Callable[[str, dict[str, Any]], PluginContext],
    ) -> None:
        self._managed: dict[str, ManagedPlugin] = {}
        self._event_bus = event_bus
        self._ctx_factory = ctx_factory

    @property
    def plugins(self) -> dict[str, ManagedPlugin]:
        return dict(self._managed)

    async def discover_and_load(
        self,
        loaded: dict[str, PluginInfo],
        plugin_configs: dict[str, dict],
    ) -> dict[str, PluginInfo]:
        registry = get_registered_plugins()

        for name, info in loaded.items():
            plugin_cls = registry.get(name)
            if plugin_cls is None:
                logger.warning(
                    f"Plugin '{name}' loaded but not registered — "
                    f"module must call plugins.registry.register()"
                )
                self._managed[name] = ManagedPlugin(
                    info=info,
                    state=PluginState.ERROR,
                    error=RuntimeError(f"Plugin '{name}' not registered"),
                )
                continue

            raw_cfg = plugin_configs.get(name, {})
            ctx = self._ctx_factory(name, raw_cfg)

            try:
                instance = plugin_cls()
                instance.meta.name = name
                await instance.on_load(ctx)
                self._managed[name] = ManagedPlugin(
                    info=info,
                    instance=instance,
                    state=PluginState.LOADED,
                    config=raw_cfg,
                )
                logger.info(f"Plugin loaded: {name} v{instance.meta.version}")
                self._event_bus.emit("plugin.loaded", name=name)
            except Exception as exc:
                logger.opt(exception=True).error(f"Failed to load plugin: {name}")
                self._managed[name] = ManagedPlugin(
                    info=info, state=PluginState.ERROR, error=exc, config=raw_cfg
                )
                self._event_bus.emit("plugin.error", name=name, error=exc)

        return loaded

    async def enable_plugin(self, name: str) -> None:
        managed = self._managed.get(name)
        if managed is None:
            logger.warning(f"Cannot enable unknown plugin: {name}")
            return
        if managed.state != PluginState.LOADED:
            logger.warning(
                f"Cannot enable plugin '{name}' in state {managed.state.name}"
            )
            return
        if managed.instance is None:
            return

        try:
            await managed.instance.on_enable()
            managed.state = PluginState.ENABLED
            logger.info(f"Plugin enabled: {name}")
            self._event_bus.emit("plugin.enabled", name=name)
        except Exception as exc:
            logger.opt(exception=True).error(f"Failed to enable plugin: {name}")
            managed.state = PluginState.ERROR
            managed.error = exc
            self._event_bus.emit("plugin.error", name=name, error=exc)

    async def disable_plugin(self, name: str) -> None:
        managed = self._managed.get(name)
        if managed is None:
            return
        if managed.state != PluginState.ENABLED:
            return
        if managed.instance is None:
            return

        try:
            await managed.instance.on_disable()
            managed.state = PluginState.DISABLED
            logger.info(f"Plugin disabled: {name}")
            self._event_bus.emit("plugin.disabled", name=name)
        except Exception as exc:
            logger.opt(exception=True).error(f"Failed to disable plugin: {name}")
            managed.state = PluginState.ERROR
            managed.error = exc
            self._event_bus.emit("plugin.error", name=name, error=exc)

    async def reload_plugin(self, name: str) -> None:
        managed = self._managed.get(name)
        if managed is None:
            logger.warning(f"Cannot reload unknown plugin: {name}")
            return

        if managed.state == PluginState.ENABLED:
            await self.disable_plugin(name)

        if managed.instance is not None:
            try:
                await managed.instance.on_unload()
            except Exception:
                logger.opt(exception=True).warning(
                    f"Error during unload of plugin '{name}'"
                )

        registry = get_registered_plugins()
        plugin_cls = registry.get(name)
        if plugin_cls is None:
            logger.error(f"Cannot reload plugin '{name}': not in registry")
            managed.state = PluginState.ERROR
            managed.error = RuntimeError(f"Plugin '{name}' not in registry")
            return

        raw_cfg = managed.config

        ctx = self._ctx_factory(name, raw_cfg)

        try:
            instance = plugin_cls()
            instance.meta.name = name
            await instance.on_load(ctx)
            managed.instance = instance
            managed.state = PluginState.LOADED
            managed.error = None
            logger.info(f"Plugin reloaded: {name}")
        except Exception as exc:
            logger.opt(exception=True).error(f"Failed to reload plugin: {name}")
            managed.state = PluginState.ERROR
            managed.error = exc
            self._event_bus.emit("plugin.error", name=name, error=exc)

    async def unload_plugin(self, name: str) -> None:
        managed = self._managed.get(name)
        if managed is None:
            return

        if managed.state == PluginState.ENABLED:
            await self.disable_plugin(name)

        if managed.instance is not None:
            try:
                await managed.instance.on_unload()
            except Exception:
                logger.opt(exception=True).warning(
                    f"Error during unload of plugin '{name}'"
                )

        managed.state = PluginState.UNLOADED
        managed.instance = None
        logger.info(f"Plugin unloaded: {name}")

    def get_status(self) -> dict[str, dict[str, Any]]:
        return {
            name: {
                "state": m.state.name,
                "version": (m.instance.meta.version if m.instance else "unknown"),
                "error": str(m.error) if m.error else None,
                "source": m.info.source if m.info else "unknown",
            }
            for name, m in self._managed.items()
        }

    async def unload_all(self) -> None:
        for name in list(self._managed):
            await self.unload_plugin(name)
