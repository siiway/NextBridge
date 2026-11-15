from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from prometheus_client import generate_latest
from prometheus_client.core import CollectorRegistry, CounterMetricFamily

import services.logger as log

logger = log.get_logger("metrics")


# name -> (label names, documentation)
_METRIC_DEFS: dict[str, tuple[tuple[str, ...], str]] = {
    "nextbridge_messages_total": (
        ("platform", "instance_id", "direction"),
        "Number of messages received from and sent to platforms.",
    ),
    "nextbridge_rule_matches_total": (
        ("rule_id",),
        "Number of messages matched by a routing rule.",
    ),
    "nextbridge_send_failures_total": (
        ("platform", "reason"),
        "Number of failed outbound sends.",
    ),
    "nextbridge_send_timeouts_total": (
        ("platform",),
        "Number of outbound sends that exceeded the send timeout.",
    ),
    "nextbridge_config_reloads_total": (
        ("kind", "target", "result"),
        "Number of configuration/rules reload attempts.",
    ),
    "nextbridge_driver_restarts_total": (
        ("platform", "instance_id"),
        "Number of driver restarts/rebuilds.",
    ),
}


class MetricsCollector:
    """In-memory metric counters exposed to Prometheus and persisted to the DB.

    The in-memory value map is the single source of truth. It is snapshotted
    periodically into the ``metrics_counters`` table and restored on startup so
    counters survive restarts.
    """

    def __init__(self) -> None:
        self._values: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._registry = CollectorRegistry()
        self._registry.register(self)

    def inc(self, name: str, amount: int = 1, **labels: str) -> None:
        if name not in _METRIC_DEFS:
            raise KeyError(f"Unknown metric: {name}")
        key = (name, tuple(sorted((str(k), str(v)) for k, v in labels.items())))
        self._values[key] = self._values.get(key, 0.0) + amount

    def get(self, name: str, **labels: str) -> float:
        key = (name, tuple(sorted((str(k), str(v)) for k, v in labels.items())))
        return self._values.get(key, 0.0)

    # Convenience wrappers -------------------------------------------------
    def inc_message(self, platform: str, instance_id: str, direction: str) -> None:
        self.inc(
            "nextbridge_messages_total",
            platform=platform,
            instance_id=instance_id,
            direction=direction,
        )

    def inc_rule_match(self, rule_id: str) -> None:
        self.inc("nextbridge_rule_matches_total", rule_id=rule_id)

    def inc_send_failure(self, platform: str, reason: str) -> None:
        self.inc("nextbridge_send_failures_total", platform=platform, reason=reason)

    def inc_send_timeout(self, platform: str) -> None:
        self.inc("nextbridge_send_timeouts_total", platform=platform)

    def inc_config_reload(self, kind: str, target: str, result: str) -> None:
        self.inc(
            "nextbridge_config_reloads_total",
            kind=kind,
            target=target,
            result=result,
        )

    def inc_driver_restart(self, platform: str, instance_id: str) -> None:
        self.inc(
            "nextbridge_driver_restarts_total",
            platform=platform,
            instance_id=instance_id,
        )

    # Prometheus exposition ------------------------------------------------
    def collect(self):
        grouped: dict[str, list[tuple[dict[str, str], float]]] = {}
        for (name, labels), value in self._values.items():
            grouped.setdefault(name, []).append((dict(labels), value))

        for name, (label_names, documentation) in _METRIC_DEFS.items():
            family = CounterMetricFamily(name, documentation, labels=list(label_names))
            for labels, value in grouped.get(name, []):
                family.add_metric([labels.get(k, "") for k in label_names], value)
            yield family

    def render(self) -> bytes:
        return generate_latest(self._registry)

    # Persistence ----------------------------------------------------------
    def snapshot(self) -> list[dict[str, Any]]:
        now = int(time.time())
        return [
            {
                "name": name,
                "labels": json.dumps(dict(labels), sort_keys=True),
                "value": value,
                "updated_at": now,
            }
            for (name, labels), value in self._values.items()
        ]

    def restore(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            try:
                labels = json.loads(row.get("labels") or "{}")
            except (TypeError, ValueError):
                logger.warning(f"Skipping malformed metric row: {row!r}")
                continue
            self.inc(str(row["name"]), int(row.get("value", 0)), **labels)


_DEFAULT_SNAPSHOT_INTERVAL = 60


async def snapshot_loop(
    metrics: MetricsCollector,
    interval: int = _DEFAULT_SNAPSHOT_INTERVAL,
) -> None:
    """Periodically persist in-memory counters into the database."""
    if interval <= 0:
        return
    from services.db import msg_db

    while True:
        await asyncio.sleep(interval)
        try:
            db = msg_db()
            await asyncio.to_thread(db.save_metrics_counters, metrics.snapshot())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.opt(exception=True).warning("Failed to snapshot metrics")
