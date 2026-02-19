import asyncio
import json
from pathlib import Path

import services.error  # installs global uncaught-exception hook
import services.logger as log
import services.util as u
from services.bridge import bridge

from drivers.napcat import NapCatDriver
from drivers.discord import DiscordDriver
from drivers.telegram import TelegramDriver
from drivers.feishu import FeishuDriver
from drivers.dingtalk import DingTalkDriver

l = log.get_logger()

DRIVER_MAP = {
    "napcat": NapCatDriver,
    "discord": DiscordDriver,
    "telegram": TelegramDriver,
    "feishu": FeishuDriver,
    "dingtalk": DingTalkDriver,
}


async def main():
    l.info("NextBridge starting…")

    bridge.load_rules()

    config_path = Path(u.get_data_path()) / "config.json"
    if not config_path.is_file():
        l.critical(f"Config file not found: {config_path}")
        return

    with open(config_path, "r", encoding="utf-8") as f:
        config: dict = json.load(f)

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
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
