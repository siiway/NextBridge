from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from drivers import BaseDriver, DriverHealth
from services.driver_manager import DriverManager, DriverState
from services.event_bus import EventBus


class FakeDriver(BaseDriver):
    def __init__(self, instance_id, config, ctx, *, fail_start=False, fail_init=False):
        super().__init__(instance_id, config, ctx)
        self.fail_start = fail_start
        self.fail_init = fail_init
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True
        if self.fail_start:
            raise RuntimeError("boom")
        await asyncio.Event().wait()

    async def stop(self):
        self.stopped = True

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


@pytest_asyncio.fixture
async def env():
    event_bus = EventBus()
    manager = DriverManager(event_bus, health_check_interval=0)
    ctx = FakeCtx()
    manager.set_context(ctx)
    yield manager, ctx
    await manager.stop_all()


@pytest.mark.asyncio
async def test_register_and_start(env):
    manager, ctx = env
    drv = FakeDriver("i1", None, ctx)
    await manager.register_and_start("fake", "i1", drv, "cfg")
    await asyncio.sleep(0)
    managed = manager.drivers["i1"]
    assert managed.state == DriverState.RUNNING
    assert managed.driver.health == DriverHealth.HEALTHY
    assert drv.started


@pytest.mark.asyncio
async def test_reload_driver_rebuilds_and_clears(env):
    manager, ctx = env
    drv = FakeDriver("i1", None, ctx)

    def factory(iid, cfg):
        return FakeDriver(iid, cfg, ctx)

    await manager.register_and_start("fake", "i1", drv, "cfg", factory)
    await asyncio.sleep(0)

    await manager.reload_driver("i1", "cfg2")
    await asyncio.sleep(0)

    managed = manager.drivers["i1"]
    assert managed.driver is not drv
    assert managed.driver.config == "cfg2"
    assert ctx.bridge.cleared == ["i1"]


@pytest.mark.asyncio
async def test_reload_driver_rolls_back_on_factory_error(env):
    manager, ctx = env

    def factory(iid, cfg):
        if cfg == "bad":
            raise ValueError("bad config")
        return FakeDriver(iid, cfg, ctx)

    drv = FakeDriver("i1", None, ctx)
    await manager.register_and_start("fake", "i1", drv, "cfg", factory)
    await asyncio.sleep(0)

    with pytest.raises(ValueError):
        await manager.reload_driver("i1", "bad")
    await asyncio.sleep(0)

    managed = manager.drivers["i1"]
    assert managed.driver is drv
    assert managed.config_snapshot == "cfg"
    assert managed.state == DriverState.RUNNING


@pytest.mark.asyncio
async def test_reload_driver_rolls_back_on_start_failure(env):
    manager, ctx = env

    def factory(iid, cfg):
        return FakeDriver(iid, cfg, ctx, fail_start=(cfg == "boom"))

    drv = FakeDriver("i1", None, ctx)
    await manager.register_and_start("fake", "i1", drv, "cfg", factory)
    await asyncio.sleep(0)

    with pytest.raises(RuntimeError):
        await manager.reload_driver("i1", "boom")
    await asyncio.sleep(0)

    managed = manager.drivers["i1"]
    assert managed.driver is drv
    assert managed.config_snapshot == "cfg"
    assert managed.state == DriverState.RUNNING


@pytest.mark.asyncio
async def test_reload_unknown_driver_raises(env):
    manager, _ = env
    with pytest.raises(KeyError):
        await manager.reload_driver("nope")
