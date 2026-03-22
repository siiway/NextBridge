import argparse
import asyncio
import importlib
import importlib.util
import sys
from pathlib import Path

from pydantic import ValidationError
from tomllib import load as load_toml

import services.error  # noqa: F401
import services.logger as log
import services.util as u
import services.config_io as config_io
from services.config_schema import GlobalConfig
from services.bridge import bridge

logger = log.get_logger()


def _load_all_drivers(enabled_platforms: list[str]) -> None:
    """Import every module in the ``drivers/`` package.

    Each driver module calls ``drivers.registry.register()`` at import time,
    so this one pass is enough to populate the registry.  The ``registry``
    module itself is skipped to avoid a circular bootstrap.
    """
    for platform in enabled_platforms:
        module_name = f"drivers.{platform}"
        if importlib.util.find_spec(module_name) is None:
            logger.warning(
                f"Driver module for platform '{platform}' not found, skipping."
            )
            continue
        importlib.import_module(module_name)


def cmd_convert(src: str, dst: str) -> None:
    src_path = Path(src)
    dst_path = Path(dst)

    if not src_path.is_file():
        logger.error(f"Source file not found: {src_path}")
        sys.exit(1)

    try:
        data = config_io.load_config(src_path)
    except:
        logger.opt(exception=True).critical(f"Error reading {src_path}")
        sys.exit(1)

    try:
        config_io.save_config(data, dst_path)
    except:
        logger.opt(exception=True).critical(f"Error reading {dst_path}")
        sys.exit(1)

    print(f"Converted {src_path} → {dst_path}")


async def main():
    config_path = config_io.find_config(Path(u.get_data_path()))
    if config_path is None:
        logger.critical(
            f"No config file found in: {u.get_data_path()} (tried config.json / .yaml / .toml)"
        )
        return

    bridge.load_rules()

    logger.info(f"Loading config from: {config_path}")
    raw: dict = config_io.load_config(config_path)

    bridge.load_sensitive_values(raw)

    enabled_platforms = [key for key in raw.keys() if key != "global"]
    _load_all_drivers(enabled_platforms)
    from drivers.registry import all_drivers

    logger.info("NextBridge starting…")

    # Load global configuration
    global_config = raw.get("global", {})
    bridge.strict_echo_match = global_config.get("strict_echo_match", False)

    # Validate database configuration

    try:
        validated_global = GlobalConfig.model_validate(global_config)
    except ValidationError as exc:
        logger.opt(exception=exc).critical("Global configuration error")
        return

    # Logging configuration
    log.set_console_level(validated_global.log.level)
    log.set_log_dir(validated_global.log.dir)
    log.set_log_rotation(
        rotation_size=validated_global.log.rotation_size,
        retention_days=validated_global.log.retention_days,
        compression=validated_global.log.compression,
        file_level=validated_global.log.file_level,
    )

    # Validate each driver's per-instance configs via its registered model.
    registry = all_drivers()
    validated: dict[str, dict[str, object]] = {}
    config_ok = True

    for platform, (config_cls, _) in registry.items():
        for inst_id, inst_raw in raw.get(platform, {}).items():
            try:
                validated.setdefault(platform, {})[inst_id] = config_cls.model_validate(
                    inst_raw
                )
            except ValidationError as exc:
                logger.opt(exception=exc).critical(
                    f"Config error in {platform}.{inst_id}"
                )
                config_ok = False

    if not config_ok:
        return

    def _on_task_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.opt(exception=exc).error(f"Driver '{task.get_name()}' crashed")

    try:
        # get version info
        with open('pyproject.toml', 'rb', encoding='utf-8') as f:
            version: str = load_toml(f).get('project', {}).get('version', 'UNKNOWN')
            f.close()
    except:
        logger.warning(f'Read version info failed', exc_info=True)
        version = 'UNKNOWN'

    logger.info(f"========== NextBridge v{version} Starting ==========")

    driver_tasks: list[asyncio.Task] = []
    for platform, (_, driver_cls) in registry.items():
        for inst_id, cfg in validated.get(platform, {}).items():
            drv = driver_cls(inst_id, cfg, bridge)
            task = asyncio.create_task(drv.start(), name=f"{platform}/{inst_id}")
            task.add_done_callback(_on_task_done)
            driver_tasks.append(task)
            logger.info(f"Registered driver: {platform}/{inst_id}")

    if not driver_tasks:
        logger.error("No drivers configured — nothing to do, exiting.")
        return

    try:
        results = await asyncio.gather(*driver_tasks, return_exceptions=True)
        for task, result in zip(driver_tasks, results):
            if isinstance(result, Exception):
                logger.error(f"Driver '{task.get_name()}' exited with error: {result}")
    except asyncio.CancelledError:
        logger.info("NextBridge shutting down…")
        # Close all aiohttp sessions to avoid connection leaks
        from services.media import close_all_sessions

        await close_all_sessions()

        logger.info("NextBridge stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="nextbridge", description="NextBridge chat bridge"
    )
    subparsers = parser.add_subparsers(dest="command")

    conv = subparsers.add_parser(
        "convert", help="Convert a config file between formats (json/yaml/toml)"
    )
    conv.add_argument("src", help="Source config file (e.g. config.json)")
    conv.add_argument("dst", help="Destination config file (e.g. config.yaml)")

    args = parser.parse_args()

    if args.command == "convert":
        cmd_convert(args.src, args.dst)
        sys.exit(0)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
