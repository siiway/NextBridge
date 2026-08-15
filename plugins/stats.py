from __future__ import annotations

from plugins import BasePlugin, PluginMeta
from plugins.registry import register


class StatsPlugin(BasePlugin):
    meta = PluginMeta(
        name="stats",
        version="1.0.0",
        display_name="Message Stats",
        description="Count bridged messages and report via /<prefix> stats",
        author="NextBridge",
    )

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._counts: dict[str, int] = {}
        self._bridge = ctx.bridge

    async def _on_message(self, instance_id: str, **kwargs) -> None:
        platform = kwargs.get("platform") or "unknown"
        self._counts[platform] = self._counts.get(platform, 0) + 1

    async def _handle_stats(self, msg, args) -> None:
        if not self._counts:
            await self._bridge.send_message(
                msg.instance_id, msg.channel, "No bridged messages recorded yet."
            )
            return

        total = sum(self._counts.values())
        lines = [f"Bridged messages: {total}"]
        for platform, count in sorted(self._counts.items()):
            lines.append(f"- {platform}: {count}")
        await self._bridge.send_message(msg.instance_id, msg.channel, "\n".join(lines))

    async def on_enable(self) -> None:
        self._ctx.event_bus.on("bridge.message", self._on_message)
        self._bridge.register_command("stats", self._handle_stats)

    async def on_disable(self) -> None:
        self._ctx.event_bus.off("bridge.message", self._on_message)
        self._bridge.unregister_command("stats")


register("stats", StatsPlugin)
