import argparse
import asyncio
import importlib
import pkgutil
import sys
from pathlib import Path

from pydantic import ValidationError

import services.error  # installs global uncaught-exception hook
import services.logger as log
import services.util as u
import services.config_io as config_io
from services.bridge import bridge

import drivers as _drivers_pkg

l = log.get_logger()


def _load_all_drivers() -> None:
    """Import every module in the ``drivers/`` package.

    Each driver module calls ``drivers.registry.register()`` at import time,
    so this one pass is enough to populate the registry.  The ``registry``
    module itself is skipped to avoid a circular bootstrap.
    """
    for _, mod_name, _ in pkgutil.iter_modules(_drivers_pkg.__path__):
        if mod_name != "registry":
            importlib.import_module(f"drivers.{mod_name}")


def cmd_convert(src: str, dst: str) -> None:
    src_path = Path(src)
    dst_path = Path(dst)

    if not src_path.is_file():
        print(f"Error: source file not found: {src_path}", file=sys.stderr)
        sys.exit(1)

    try:
        data = config_io.load_config(src_path)
    except Exception as e:
        print(f"Error reading {src_path}: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        config_io.save_config(data, dst_path)
    except Exception as e:
        print(f"Error writing {dst_path}: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Converted {src_path} → {dst_path}")


async def main():
    _load_all_drivers()
    from drivers.registry import all_drivers

    l.info("NextBridge starting…")

    bridge.load_rules()

    config_path = config_io.find_config(Path(u.get_data_path()))
    if config_path is None:
        l.critical(f"No config file found in: {u.get_data_path()} (tried config.json / .yaml / .toml)")
        return

    l.info(f"Loading config from: {config_path}")
    raw: dict = config_io.load_config(config_path)

    bridge.load_sensitive_values(raw)

    # Validate each driver's per-instance configs via its registered model.
    registry = all_drivers()
    validated: dict[str, dict[str, object]] = {}
    config_ok = True

    for platform, (config_cls, _) in registry.items():
        for inst_id, inst_raw in raw.get(platform, {}).items():
            try:
                validated.setdefault(platform, {})[inst_id] = config_cls.model_validate(inst_raw)
            except ValidationError as exc:
                l.critical(f"Config error in {platform}.{inst_id}:\n{exc}")
                config_ok = False

    if not config_ok:
        return

    def _on_task_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            l.error(f"Driver '{task.get_name()}' crashed: {exc}")

    driver_tasks: list[asyncio.Task] = []
    for platform, (_, driver_cls) in registry.items():
        for inst_id, cfg in validated.get(platform, {}).items():
            drv = driver_cls(inst_id, cfg, bridge)
            task = asyncio.create_task(drv.start(), name=f"{platform}/{inst_id}")
            task.add_done_callback(_on_task_done)
            driver_tasks.append(task)
            l.info(f"Registered driver: {platform}/{inst_id}")

    if not driver_tasks:
        l.error("No drivers configured — nothing to do, exiting.")
        return

    try:
        results = await asyncio.gather(*driver_tasks, return_exceptions=True)
        for task, result in zip(driver_tasks, results):
            if isinstance(result, Exception):
                l.error(f"Driver '{task.get_name()}' exited with error: {result}")
    except asyncio.CancelledError:
        l.info("NextBridge shutting down…")
        for task in driver_tasks:
            task.cancel()
        await asyncio.gather(*driver_tasks, return_exceptions=True)
        l.info("NextBridge stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="nextbridge", description="NextBridge chat bridge")
    subparsers = parser.add_subparsers(dest="command")

    conv = subparsers.add_parser("convert", help="Convert a config file between formats (json/yaml/toml)")
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
