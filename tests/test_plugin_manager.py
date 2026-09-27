from __future__ import annotations

from unittest.mock import patch

import pytest

from plugins import BasePlugin, PluginMeta, PluginState
from plugins.context import PluginContext
from plugins.loader import PluginInfo
from plugins.manager import PluginDependencyError, PluginError, PluginManager
from services.bridge import Bridge
from services.event_bus import EventBus
from services.middleware import MiddlewareChain


class RecordingPlugin(BasePlugin):
    meta = PluginMeta(name="rec", version="1.0.0")

    def __init__(self):
        self.enabled = False

    async def on_load(self, ctx) -> None:
        self.ctx = ctx

    async def on_enable(self) -> None:
        self.enabled = True
        self.ctx.register_command("rec", self._handler)
        self.ctx.on_event("evt", self._handler)

    async def on_disable(self) -> None:
        self.enabled = False

    async def _handler(self, *args, **kwargs) -> None:
        pass


class DependentPlugin(BasePlugin):
    meta = PluginMeta(name="dep", version="1.0.0", dependencies=["rec"])

    async def on_load(self, ctx) -> None:
        self.ctx = ctx


class FailingPlugin(BasePlugin):
    meta = PluginMeta(name="fail", version="1.0.0")

    async def on_load(self, ctx) -> None:
        ctx.register_command("failcmd", self._handler)
        raise RuntimeError("boom")

    async def _handler(self, *args, **kwargs) -> None:
        pass


class FlakyPlugin(BasePlugin):
    meta = PluginMeta(name="flaky", version="1.0.0")
    fail_next = False

    async def on_load(self, ctx) -> None:
        self.ctx = ctx
        if FlakyPlugin.fail_next:
            FlakyPlugin.fail_next = False
            raise RuntimeError("boom")

    async def on_enable(self) -> None:
        self.ctx.register_command("flaky", self._handler)

    async def _handler(self, *args, **kwargs) -> None:
        pass


class FailingDisablePlugin(BasePlugin):
    meta = PluginMeta(name="faildis", version="1.0.0")

    async def on_load(self, ctx) -> None:
        self.ctx = ctx

    async def on_enable(self) -> None:
        self.ctx.register_command("faildis", self._handler)

    async def on_disable(self) -> None:
        raise RuntimeError("boom")

    async def _handler(self, *args, **kwargs) -> None:
        pass


def _ctx_factory(bridge, event_bus, middleware):
    def factory(name, cfg):
        return PluginContext(
            bridge=bridge, event_bus=event_bus, middleware=middleware, config=cfg
        )

    return factory


class TestPluginContextCleanup:
    def test_cleanup_removes_registrations(self):
        bridge = Bridge()
        event_bus = EventBus()
        middleware = MiddlewareChain()
        ctx = PluginContext(bridge=bridge, event_bus=event_bus, middleware=middleware)

        ctx.register_command("rec", lambda *a: None)
        ctx.on_event("evt", lambda *a: None)
        ctx.add_receive_middleware("mw", lambda m: m)

        assert "rec" in bridge._commands
        assert event_bus._handlers["evt"]
        assert middleware.has_receive

        ctx.cleanup()

        assert "rec" not in bridge._commands
        assert not event_bus._handlers["evt"]
        assert not middleware.has_receive

    def test_cleanup_is_idempotent(self):
        ctx = PluginContext(bridge=Bridge(), event_bus=EventBus())
        ctx.register_command("rec", lambda *a: None)
        ctx.cleanup()
        ctx.cleanup()


class TestPluginManagerLifecycle:
    @pytest.fixture
    def env(self):
        bridge = Bridge()
        event_bus = EventBus()
        middleware = MiddlewareChain()
        manager = PluginManager(event_bus, _ctx_factory(bridge, event_bus, middleware))
        return bridge, event_bus, middleware, manager

    @pytest.mark.asyncio
    async def test_disable_cleans_registrations(self, env):
        bridge, _, _, manager = env
        registry = {"rec": RecordingPlugin}
        loaded = {"rec": PluginInfo(name="rec", source="test", module_path="x")}
        with patch("plugins.manager.get_registered_plugins", return_value=registry):
            await manager.discover_and_load(loaded, {})
            await manager.enable_plugin("rec")
            assert "rec" in bridge._commands
            await manager.disable_plugin("rec")
        assert "rec" not in bridge._commands
        assert manager.plugins["rec"].state == PluginState.DISABLED

    @pytest.mark.asyncio
    async def test_restart_reloads_and_reenables(self, env):
        bridge, _, _, manager = env
        registry = {"rec": RecordingPlugin}
        loaded = {"rec": PluginInfo(name="rec", source="test", module_path="x")}
        with patch("plugins.manager.get_registered_plugins", return_value=registry):
            await manager.discover_and_load(loaded, {})
            await manager.enable_plugin("rec")
            first = manager.plugins["rec"].instance
            await manager.restart_plugin("rec")
        managed = manager.plugins["rec"]
        assert managed.state == PluginState.ENABLED
        assert managed.instance is not first
        assert "rec" in bridge._commands

    @pytest.mark.asyncio
    async def test_unload_clears_instance(self, env):
        _, _, _, manager = env
        registry = {"rec": RecordingPlugin}
        loaded = {"rec": PluginInfo(name="rec", source="test", module_path="x")}
        with patch("plugins.manager.get_registered_plugins", return_value=registry):
            await manager.discover_and_load(loaded, {})
            await manager.unload_plugin("rec")
        managed = manager.plugins["rec"]
        assert managed.state == PluginState.UNLOADED
        assert managed.instance is None
        assert managed.ctx is None

    @pytest.mark.asyncio
    async def test_failed_load_cleans_registrations(self, env):
        bridge, _, _, manager = env
        registry = {"fail": FailingPlugin}
        loaded = {"fail": PluginInfo(name="fail", source="test", module_path="x")}
        with patch("plugins.manager.get_registered_plugins", return_value=registry):
            await manager.discover_and_load(loaded, {})
        assert "failcmd" not in bridge._commands
        managed = manager.plugins["fail"]
        assert managed.state == PluginState.ERROR
        assert managed.instance is None
        assert managed.ctx is None

    @pytest.mark.asyncio
    async def test_disable_cleans_when_hook_fails(self, env):
        bridge, _, _, manager = env
        registry = {"faildis": FailingDisablePlugin}
        loaded = {"faildis": PluginInfo(name="faildis", source="test", module_path="x")}
        with patch("plugins.manager.get_registered_plugins", return_value=registry):
            await manager.discover_and_load(loaded, {})
            await manager.enable_plugin("faildis")
            assert "faildis" in bridge._commands
            await manager.disable_plugin("faildis")
        assert "faildis" not in bridge._commands
        assert manager.plugins["faildis"].state == PluginState.ERROR

    @pytest.mark.asyncio
    async def test_restart_failure_keeps_old_instance(self, env):
        bridge, _, _, manager = env
        registry = {"flaky": FlakyPlugin}
        loaded = {"flaky": PluginInfo(name="flaky", source="test", module_path="x")}
        with patch("plugins.manager.get_registered_plugins", return_value=registry):
            await manager.discover_and_load(loaded, {})
            await manager.enable_plugin("flaky")
            first = manager.plugins["flaky"].instance
            assert "flaky" in bridge._commands
            FlakyPlugin.fail_next = True
            with pytest.raises(PluginError):
                await manager.restart_plugin("flaky")
        managed = manager.plugins["flaky"]
        assert managed.instance is first
        assert managed.state == PluginState.ENABLED
        assert "flaky" in bridge._commands

    @pytest.mark.asyncio
    async def test_dependency_refusal(self, env):
        _, _, _, manager = env
        registry = {"rec": RecordingPlugin, "dep": DependentPlugin}
        loaded = {
            "rec": PluginInfo(name="rec", source="test", module_path="x"),
            "dep": PluginInfo(name="dep", source="test", module_path="y"),
        }
        with patch("plugins.manager.get_registered_plugins", return_value=registry):
            await manager.discover_and_load(loaded, {})
            await manager.enable_plugin("rec")
            await manager.enable_plugin("dep")
            with pytest.raises(PluginDependencyError):
                await manager.disable_plugin("rec")
