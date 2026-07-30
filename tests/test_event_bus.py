from __future__ import annotations

import asyncio

import pytest

from services.event_bus import EventBus


class TestEventBus:
    @pytest.mark.asyncio
    async def test_on_and_emit_await(self):
        bus = EventBus()
        results: list[dict] = []

        async def handler(**kwargs):
            results.append(kwargs)

        bus.on("test.event", handler)
        await bus.emit_await("test.event", foo="bar")
        assert results == [{"foo": "bar"}]

    @pytest.mark.asyncio
    async def test_off(self):
        bus = EventBus()
        results: list[dict] = []

        async def handler(**kwargs):
            results.append(kwargs)

        bus.on("test.event", handler)
        bus.off("test.event", handler)
        await bus.emit_await("test.event", foo="bar")
        assert results == []

    @pytest.mark.asyncio
    async def test_multiple_handlers(self):
        bus = EventBus()
        results: list[str] = []

        async def h1(**kwargs):
            results.append("h1")

        async def h2(**kwargs):
            results.append("h2")

        bus.on("test.event", h1)
        bus.on("test.event", h2)
        await bus.emit_await("test.event")
        assert results == ["h1", "h2"]

    @pytest.mark.asyncio
    async def test_handler_error_does_not_propagate(self):
        bus = EventBus()

        async def broken(**kwargs):
            raise ValueError("oops")

        bus.on("test.event", broken)
        await bus.emit_await("test.event")

    @pytest.mark.asyncio
    async def test_emit_fire_and_forget(self):
        bus = EventBus()
        results: list[str] = []

        async def handler(**kwargs):
            results.append("called")

        bus.on("test.event", handler)
        bus.emit("test.event")
        await asyncio.sleep(0.05)
        assert results == ["called"]

    @pytest.mark.asyncio
    async def test_no_handlers_no_error(self):
        bus = EventBus()
        await bus.emit_await("nonexistent.event")
