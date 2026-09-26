from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import services.config as config
from drivers import BaseDriver
from drivers.registry import register, unregister
from services.bridge import Bridge
from services.config_schema import _DriverConfig
from services.driver_manager import DriverManager
from services.event_bus import EventBus
from services.reload import ReloadEngine, ReloadError


class ReloadCfg(_DriverConfig):
    token: str


class ReloadDriver(BaseDriver):
    async def start(self):
        await asyncio.Event().wait()

    async def stop(self):
        pass

    async def send(self, channel, text, **kwargs):
        return None


class FakeBridge:
    def __init__(self):
        self.cleared: list[str] = []

    def clear_instance(self, instance_id):
        self.cleared.append(instance_id)


class FakeCtx:
    def __init__(self):
        self.bridge = FakeBridge()


def _write_rules(path: Path, rules: list[dict]) -> None:
    path.write_text(json.dumps({"rules": rules}), encoding="utf-8")


def _write_config(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    rules_path = tmp_path / "rules.yaml"
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, {"global": {"command_prefix": "nb"}})
    monkeypatch.setattr("services.reload.config_io.find_rules", lambda _d: rules_path)
    bridge = Bridge()
    engine = ReloadEngine(bridge, config_path=config_path)
    return bridge, engine, rules_path, config_path


@pytest.mark.asyncio
async def test_reload_rules_applies(env):
    bridge, engine, rules_path, _ = env
    _write_rules(rules_path, [{"id": "r1", "type": "forward", "from": {}, "to": {}}])
    rules = await engine.reload_rules()
    assert len(rules) == 1
    assert [r["id"] for r in bridge._rules] == ["r1"]


@pytest.mark.asyncio
async def test_reload_rules_invalid_keeps_old(env):
    bridge, engine, rules_path, _ = env
    _write_rules(rules_path, [{"id": "r1", "type": "forward"}])
    await engine.reload_rules()
    old = bridge._rules

    _write_rules(rules_path, [{"id": "r2", "type": "bogus"}])
    with pytest.raises(ReloadError) as exc:
        await engine.reload_rules()
    assert exc.value.code == "invalid_rules"
    assert bridge._rules is old


@pytest.mark.asyncio
async def test_reload_config_applies_hot_keys(env):
    bridge, engine, _, config_path = env
    _write_config(
        config_path,
        {
            "global": {
                "command_prefix": "cfg",
                "send_timeout": 5.0,
                "strict_echo_match": True,
            }
        },
    )
    await engine.reload_config()
    assert bridge.command_prefix == "cfg"
    assert bridge.send_timeout == 5.0
    assert bridge.strict_echo_match is True
    assert config.get("global.command_prefix") == "cfg"


@pytest.mark.asyncio
async def test_reload_drivers_validates_before_rebuild(env):
    _, engine, _, config_path = env
    register("reloadtest", ReloadCfg, ReloadDriver)
    try:
        ctx = FakeCtx()
        manager = DriverManager(EventBus(), health_check_interval=0)
        manager.set_context(ctx)
        drv = ReloadDriver("i1", None, ctx)
        await manager.register_and_start("reloadtest", "i1", drv, None, lambda i, c: c)
        await asyncio.sleep(0)
        engine._driver_manager = manager

        _write_config(config_path, {"reloadtest": {"i1": {}}})
        with pytest.raises(ReloadError) as exc:
            await engine.reload_drivers()
        assert exc.value.code == "invalid_driver_config"
        assert manager.drivers["i1"].driver is drv

        await manager.stop_all()
    finally:
        unregister("reloadtest")


@pytest.mark.asyncio
async def test_reload_drivers_rebuilds_changed(env):
    _, engine, _, config_path = env
    register("reloadtest", ReloadCfg, ReloadDriver)
    try:
        ctx = FakeCtx()
        manager = DriverManager(EventBus(), health_check_interval=0)
        manager.set_context(ctx)
        drv = ReloadDriver("i1", None, ctx)
        await manager.register_and_start(
            "reloadtest", "i1", drv, None, lambda i, c: ReloadDriver(i, c, ctx)
        )
        await asyncio.sleep(0)
        engine._driver_manager = manager

        raw = {"reloadtest": {"i1": {"token": "a"}}}
        _write_config(config_path, raw)
        engine.seed(raw)
        assert await engine.reload_drivers() == []

        _write_config(config_path, {"reloadtest": {"i1": {"token": "b"}}})
        assert await engine.reload_drivers() == ["i1"]
        assert ctx.bridge.cleared == ["i1"]
        assert manager.drivers["i1"].driver is not drv

        await manager.stop_all()
    finally:
        unregister("reloadtest")


@pytest.mark.asyncio
async def test_reload_all(env):
    bridge, engine, rules_path, _ = env
    _write_rules(rules_path, [{"id": "r1", "type": "forward"}])
    result = await engine.reload_all()
    assert result["rules"] == 1
    assert bridge.command_prefix == "nb"


@pytest.mark.asyncio
async def test_reload_all_invalid_rules_keeps_global(env):
    bridge, engine, rules_path, config_path = env
    _write_config(config_path, {"global": {"command_prefix": "first"}})
    await engine.reload_config()
    assert bridge.command_prefix == "first"

    # A new global config is valid, but the rules file is not: nothing
    # must be applied, including the global config.
    _write_config(config_path, {"global": {"command_prefix": "second"}})
    _write_rules(rules_path, [{"id": "r1", "type": "bogus"}])
    with pytest.raises(ReloadError) as exc:
        await engine.reload_all()
    assert exc.value.code == "invalid_rules"
    assert bridge.command_prefix == "first"
    assert config.get("global.command_prefix") == "first"


def test_startup_rules_validation(tmp_path, monkeypatch):
    rules_path = tmp_path / "rules.yaml"
    _write_rules(rules_path, [{"id": "r1", "type": "bogus"}])
    monkeypatch.setattr("services.config.config_io.find_rules", lambda _d: rules_path)
    with pytest.raises(config.RulesValidationError):
        Bridge().load_rules()
