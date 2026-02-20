import argparse
import asyncio
import sys
from pathlib import Path

import services.error  # installs global uncaught-exception hook
import services.logger as log
import services.util as u
import services.config_io as config_io
from services.bridge import bridge

from drivers.napcat import NapCatDriver
from drivers.discord import DiscordDriver
from drivers.telegram import TelegramDriver
from drivers.feishu import FeishuDriver
from drivers.dingtalk import DingTalkDriver
from drivers.yunhu import YunhuDriver
from drivers.kook import KookDriver

l = log.get_logger()

DRIVER_MAP = {
    "napcat": NapCatDriver,
    "discord": DiscordDriver,
    "telegram": TelegramDriver,
    "feishu": FeishuDriver,
    "dingtalk": DingTalkDriver,
    "yunhu": YunhuDriver,
    "kook": KookDriver,
}


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
    l.info("NextBridge starting…")

    bridge.load_rules()

    config_path = config_io.find_config(Path(u.get_data_path()))
    if config_path is None:
        l.critical(f"No config file found in: {u.get_data_path()} (tried config.json / .yaml / .toml)")
        return

    l.info(f"Loading config from: {config_path}")
    config: dict = config_io.load_config(config_path)

    bridge.load_sensitive_values(config)

    driver_tasks: list[asyncio.Task] = []
    for platform, instances in config.items():
        driver_cls = DRIVER_MAP.get(platform)
        if driver_cls is None:
            l.warning(f"Unknown platform '{platform}' in config — skipping")
            continue
        for instance_id, instance_cfg in instances.items():
            drv = driver_cls(instance_id, instance_cfg, bridge)
            task = asyncio.create_task(drv.start(), name=f"{platform}/{instance_id}")
            driver_tasks.append(task)
            l.info(f"Registered driver: {platform}/{instance_id}")

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
