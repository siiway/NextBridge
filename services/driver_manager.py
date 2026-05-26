from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Callable

import services.logger as log
from drivers import BaseDriver, DriverHealth
from services.event_bus import EventBus

logger = log.get_logger("driver_manager")

DEFAULT_MAX_RESTART_ATTEMPTS = 5
RESTART_BACKOFF_BASE = 2.0  # seconds
DEFAULT_HEALTH_CHECK_INTERVAL = 60  # seconds

_SKIP_STOP_STATES = frozenset(
    {
        "RESTART_PENDING",
        "STARTING",
        "RUNNING",
    }
)


class DriverState(Enum):
    CREATED = auto()
    STARTING = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()
    CRASHED = auto()
    RESTART_PENDING = auto()


@dataclass
class ManagedDriver:
    platform: str
    instance_id: str
    driver: BaseDriver
    task: asyncio.Task | None = None
    state: DriverState = DriverState.CREATED
    restart_count: int = 0
    last_error: Exception | None = None
    config_snapshot: Any = None


class DriverManager:
    """Lifecycle orchestration for all driver instances.

    Handles start/stop, health monitoring, auto-restart with exponential
    backoff, and hot-reload of individual drivers.
    """

    def __init__(
        self,
        event_bus: EventBus,
        *,
        auto_restart: bool = True,
        max_restart_attempts: int = DEFAULT_MAX_RESTART_ATTEMPTS,
        health_check_interval: int = DEFAULT_HEALTH_CHECK_INTERVAL,
    ) -> None:
        self._managed: dict[str, ManagedDriver] = {}
        self._event_bus = event_bus
        self._auto_restart = auto_restart
        self._max_restart_attempts = max_restart_attempts
        self._health_check_interval = health_check_interval
        self._health_task: asyncio.Task | None = None

    @property
    def drivers(self) -> dict[str, ManagedDriver]:
        return dict(self._managed)

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    async def register_and_start(
        self,
        platform: str,
        instance_id: str,
        driver: BaseDriver,
        config_snapshot: Any = None,
    ) -> None:
        managed = ManagedDriver(
            platform=platform,
            instance_id=instance_id,
            driver=driver,
            config_snapshot=config_snapshot,
        )
        self._managed[instance_id] = managed
        await self._start_driver(managed)

    async def _start_driver(self, managed: ManagedDriver) -> None:
        managed.state = DriverState.STARTING
        managed.driver.health = DriverHealth.STARTING
        self._event_bus.emit("driver.starting", instance_id=managed.instance_id)

        task = asyncio.create_task(
            self._run_driver(managed),
            name=f"{managed.platform}/{managed.instance_id}",
        )
        managed.task = task

    async def _run_driver(self, managed: ManagedDriver) -> None:
        try:
            managed.state = DriverState.RUNNING
            managed.driver.health = DriverHealth.HEALTHY
            self._event_bus.emit("driver.started", instance_id=managed.instance_id)
            logger.info(f"Driver '{managed.instance_id}' started")
            await managed.driver.start()
        except asyncio.CancelledError:
            managed.state = DriverState.STOPPING
            logger.info(f"Driver '{managed.instance_id}' cancelled")
        except Exception as exc:
            managed.state = DriverState.CRASHED
            managed.last_error = exc
            managed.driver.health = DriverHealth.UNHEALTHY
            logger.opt(exception=exc).error(f"Driver '{managed.instance_id}' crashed")
            self._event_bus.emit(
                "driver.crashed", instance_id=managed.instance_id, error=exc
            )

            if (
                self._auto_restart
                and managed.restart_count < self._max_restart_attempts
            ):
                managed.restart_count += 1
                delay = RESTART_BACKOFF_BASE**managed.restart_count
                managed.state = DriverState.RESTART_PENDING
                logger.info(
                    f"Restarting '{managed.instance_id}' in {delay:.0f}s "
                    f"(attempt {managed.restart_count}/{self._max_restart_attempts})"
                )
                await asyncio.sleep(delay)
                await self._start_driver(managed)
                return  # new task takes over
            else:
                logger.error(
                    f"Driver '{managed.instance_id}' exceeded max restarts, giving up"
                )
                self._event_bus.emit(
                    "driver.abandoned", instance_id=managed.instance_id
                )
        finally:
            # Skip cleanup if a restart spawned a new task (state will be
            # RESTART_PENDING or STARTING), or if start() returned normally
            # for a send-only driver (state stays RUNNING — the driver
            # instance remains alive for send() calls).
            if managed.state.name not in _SKIP_STOP_STATES:
                try:
                    await managed.driver.stop()
                except Exception:
                    logger.opt(exception=True).warning(
                        f"Error during stop of '{managed.instance_id}'"
                    )
                managed.state = DriverState.STOPPED
                managed.driver.health = DriverHealth.STOPPED
                self._event_bus.emit("driver.stopped", instance_id=managed.instance_id)

    async def stop_driver(self, instance_id: str) -> None:
        managed = self._managed.get(instance_id)
        if not managed:
            return

        # Prevent auto-restart from triggering during shutdown.
        managed.restart_count = self._max_restart_attempts

        if managed.task and not managed.task.done():
            managed.task.cancel()
            try:
                await asyncio.wait_for(managed.task, timeout=10.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        # Ensure stop() is called even for send-only drivers whose task
        # already completed (their finally block skips stop).
        if managed.state != DriverState.STOPPED:
            try:
                await managed.driver.stop()
            except Exception:
                logger.opt(exception=True).warning(
                    f"Error during stop of '{managed.instance_id}'"
                )
            managed.state = DriverState.STOPPED
            managed.driver.health = DriverHealth.STOPPED

    async def restart_driver(
        self,
        instance_id: str,
        new_config: Any = None,
        driver_factory: Callable[..., BaseDriver] | None = None,
    ) -> None:
        managed = self._managed.get(instance_id)
        if not managed:
            logger.warning(f"Cannot restart unknown driver: {instance_id}")
            return

        await self.stop_driver(instance_id)

        if new_config is not None and driver_factory is not None:
            new_driver = driver_factory(instance_id, new_config)
            managed.driver = new_driver
            managed.config_snapshot = new_config

        managed.restart_count = 0
        managed.last_error = None
        await self._start_driver(managed)
        logger.info(f"Driver '{instance_id}' restarted")

    async def stop_all(self) -> None:
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()

        tasks = [self.stop_driver(iid) for iid in list(self._managed)]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ------------------------------------------------------------------
    # Health monitoring
    # ------------------------------------------------------------------

    async def start_health_monitor(self) -> None:
        if self._health_check_interval <= 0:
            return
        self._health_task = asyncio.create_task(
            self._health_loop(), name="driver_manager/health"
        )

    async def _health_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._health_check_interval)
                for instance_id, managed in self._managed.items():
                    if managed.state != DriverState.RUNNING:
                        continue
                    try:
                        health = await asyncio.wait_for(
                            managed.driver.health_check(), timeout=5.0
                        )
                        managed.driver.health = health
                    except Exception:
                        managed.driver.health = DriverHealth.UNHEALTHY
                        logger.warning(f"Health check failed for '{instance_id}'")
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, dict[str, Any]]:
        return {
            iid: {
                "platform": m.platform,
                "state": m.state.name,
                "health": m.driver.health.value,
                "restart_count": m.restart_count,
                "error": str(m.last_error) if m.last_error else None,
            }
            for iid, m in self._managed.items()
        }
