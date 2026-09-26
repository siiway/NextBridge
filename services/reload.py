from __future__ import annotations

import asyncio
import hashlib
import json
import signal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import services.config as config
import services.config_io as config_io
import services.logger as log
import services.util as u
from pydantic import ValidationError
from services.config_schema import GlobalConfig

if TYPE_CHECKING:
    from services.bridge import Bridge
    from services.driver_manager import DriverManager

logger = log.get_logger("reload")

HOT_RELOAD_GLOBAL_KEYS = frozenset(
    {
        "command_prefix",
        "strict_echo_match",
        "fuzzy_mention_match",
        "mention_notify_control",
        "send_timeout",
    }
)
"""Global config keys that can be applied without a restart."""


class ReloadError(Exception):
    """Raised when a reload request cannot be satisfied."""

    def __init__(
        self, message: str, *, code: str = "reload_error", details: Any = None
    ):
        super().__init__(message)
        self.code = code
        self.details = details


def _hash_raw(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ReloadEngine:
    """Validation + apply pipeline for runtime configuration reloads.

    All public ``reload_*`` methods serialize on :attr:`lock` so that a
    read-modify-write cycle cannot interleave with another reload.
    """

    def __init__(
        self,
        bridge: Bridge,
        *,
        config_path: Path,
        driver_manager: DriverManager | None = None,
        metrics: Any = None,
    ) -> None:
        self._bridge = bridge
        self._config_path = Path(config_path)
        self._driver_manager = driver_manager
        self._metrics = metrics
        self.lock = asyncio.Lock()
        self._driver_hashes: dict[str, str] = {}

    def _record(self, kind: str, target: str, result: str) -> None:
        if self._metrics is not None:
            self._metrics.inc_config_reload(kind, target, result)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def read_config_file(self) -> dict:
        path = self._config_path
        if not path.exists():
            found = config_io.find_config(Path(u.get_data_path()))
            if found is None:
                raise ReloadError("No config file found", code="config_not_found")
            path = found
            self._config_path = path
        try:
            return config_io.load_config(path)
        except Exception as exc:
            raise ReloadError(
                f"Failed to parse config: {exc}", code="config_parse_error"
            ) from exc

    def read_rules_file(self) -> tuple[dict, Path | None]:
        path = config_io.find_rules(Path(u.get_data_path()))
        if path is None:
            return {}, None
        try:
            return config_io.load_config(path), path
        except Exception as exc:
            raise ReloadError(
                f"Failed to parse rules: {exc}", code="rules_parse_error"
            ) from exc

    # ------------------------------------------------------------------
    # Validation + apply
    # ------------------------------------------------------------------
    def parse_rules(self, data: Any) -> list[dict]:
        try:
            return config.parse_rules(data)
        except config.RulesValidationError as exc:
            raise ReloadError(
                str(exc), code="invalid_rules", details=exc.errors
            ) from exc

    def validate_global(self, raw: dict) -> GlobalConfig:
        try:
            return GlobalConfig.model_validate(raw.get("global", {}) or {})
        except ValidationError as exc:
            raise ReloadError(
                "Invalid global configuration",
                code="invalid_config",
                details=exc.errors(),
            ) from exc

    def apply_config(self, raw: dict) -> GlobalConfig:
        """Validate *raw* config and apply the hot-reloadable subset."""
        validated = self.validate_global(raw)
        self._bridge.load_sensitive_values(raw)
        self._bridge.command_prefix = validated.command_prefix
        self._bridge.strict_echo_match = validated.strict_echo_match
        self._bridge.fuzzy_mention_match = validated.fuzzy_mention_match
        self._bridge.mention_notify_control = validated.mention_notify_control
        self._bridge.send_timeout = validated.send_timeout
        config.apply_raw(raw, self._config_path)
        return validated

    def apply_rules(self, rules: list[dict]) -> None:
        self._bridge.apply_rules(rules)

    # ------------------------------------------------------------------
    # Reload operations
    # ------------------------------------------------------------------
    async def reload_config(self) -> GlobalConfig:
        async with self.lock:
            return self.reload_config_locked()

    def reload_config_locked(self) -> GlobalConfig:
        try:
            raw = self.read_config_file()
            validated = self.apply_config(raw)
        except ReloadError:
            self._record("config", "", "error")
            raise
        self._record("config", "", "ok")
        logger.info("Reloaded global configuration")
        return validated

    async def reload_rules(self) -> list[dict]:
        async with self.lock:
            return self.reload_rules_locked()

    def reload_rules_locked(self) -> list[dict]:
        try:
            data, _ = self.read_rules_file()
            rules = self.parse_rules(data)
        except ReloadError:
            self._record("rules", "", "error")
            raise
        self.apply_rules(rules)
        self._record("rules", "", "ok")
        logger.info(f"Reloaded {len(rules)} rule(s)")
        return rules

    async def reload_drivers(self) -> list[str]:
        async with self.lock:
            return await self.reload_drivers_locked()

    async def reload_drivers_locked(self) -> list[str]:
        """Rebuild every driver instance whose raw config changed.

        All changed configs are validated first; if any is invalid nothing
        is rebuilt and :class:`ReloadError` is raised.
        """
        from drivers.registry import all_drivers

        raw = self.read_config_file()
        registry = all_drivers()
        changed: list[tuple[str, Any, str]] = []
        errors: list[dict] = []

        for platform, (config_cls, _) in registry.items():
            for inst_id, inst_raw in (raw.get(platform, {}) or {}).items():
                digest = _hash_raw(inst_raw)
                if self._driver_hashes.get(inst_id) == digest:
                    continue
                try:
                    cfg = config_cls.model_validate(inst_raw)
                except ValidationError as exc:
                    errors.append({"instance_id": inst_id, "errors": exc.errors()})
                    continue
                changed.append((inst_id, cfg, digest))

        if errors:
            for err in errors:
                self._record("driver", str(err.get("instance_id", "")), "error")
            raise ReloadError(
                "Invalid driver configuration",
                code="invalid_driver_config",
                details=errors,
            )

        manager = self._driver_manager
        managed_ids = set(manager.drivers) if manager else set()
        reloaded: list[str] = []
        for inst_id, cfg, digest in changed:
            if manager is None or inst_id not in managed_ids:
                self._driver_hashes[inst_id] = digest
                continue
            try:
                await manager.reload_driver(inst_id, cfg)
            except Exception as exc:
                self._record("driver", inst_id, "error")
                raise ReloadError(
                    f"Failed to reload driver '{inst_id}': {exc}",
                    code="driver_reload_failed",
                    details={"instance_id": inst_id},
                ) from exc
            self._driver_hashes[inst_id] = digest
            self._record("driver", inst_id, "ok")
            reloaded.append(inst_id)

        if reloaded:
            logger.info(f"Reloaded {len(reloaded)} driver(s): {', '.join(reloaded)}")
        return reloaded

    async def reload_all(self) -> dict:
        async with self.lock:
            raw = self.read_config_file()
            validated = self.apply_config(raw)
            self._record("config", "", "ok")
            data, _ = self.read_rules_file()
            rules = self.parse_rules(data)
            self.apply_rules(rules)
            self._record("rules", "", "ok")
            reloaded = await self.reload_drivers_locked()
            logger.info("Full reload completed")
            return {
                "rules": len(rules),
                "command_prefix": validated.command_prefix,
                "drivers": reloaded,
            }

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------
    def seed(self, raw: dict | None = None) -> None:
        """Record the current per-instance config hashes as the baseline."""
        from drivers.registry import all_drivers

        if raw is None:
            raw = self.read_config_file()
        for platform in all_drivers():
            for inst_id, inst_raw in (raw.get(platform, {}) or {}).items():
                self._driver_hashes[inst_id] = _hash_raw(inst_raw)

    def note_driver_config(self, instance_id: str, inst_raw: Any) -> None:
        """Update the baseline hash after an explicit per-instance reload."""
        self._driver_hashes[instance_id] = _hash_raw(inst_raw)


async def _safe_reload_all(engine: ReloadEngine) -> None:
    try:
        await engine.reload_all()
    except ReloadError as exc:
        logger.error(f"SIGHUP reload failed: {exc}")
    except Exception:
        logger.opt(exception=True).error("SIGHUP reload failed")


def install_sighup_handler(engine: ReloadEngine) -> bool:
    """Install a SIGHUP handler that triggers a full reload.

    Returns False on platforms without signal support (e.g. Windows).
    """
    if not hasattr(signal, "SIGHUP"):
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False

    def _handler() -> None:
        asyncio.ensure_future(_safe_reload_all(engine))

    try:
        loop.add_signal_handler(signal.SIGHUP, _handler)
    except (NotImplementedError, RuntimeError):
        return False
    return True
