import argparse
import asyncio
import importlib
import importlib.util
import sys
from pathlib import Path
from tomllib import load as load_toml

from pydantic import ValidationError

import services.error  # noqa: F401
import services.logger as log
import services.util as u
from services import config_io
from services.bridge import bridge
from services.config_schema import GlobalConfig, RulesFile
from services.db import db_target_version, init_db
from services.driver_context import DriverContext
from services.driver_manager import DriverManager
from services.event_bus import EventBus
from services.http_server import HttpServerManager
from services.media import close_all_sessions
from services.middleware import MiddlewareChain
from services.plugin_loader import load_all_drivers

logger = log.get_logger("__main__")


def _load_project_version() -> str:
    try:
        with open("pyproject.toml", "rb") as f:
            version = str(load_toml(f).get("project", {}).get("version", "")).strip()
    except Exception as exc:
        raise RuntimeError("Read version info failed") from exc

    if not version:
        raise RuntimeError("Missing [project].version in pyproject.toml")

    return version


def _discover_all_driver_modules() -> None:
    """Import every .py in drivers/ to discover CLI hooks and registrations."""
    drivers_dir = Path(__file__).parent / "drivers"
    if not drivers_dir.is_dir():
        return
    for py_file in sorted(drivers_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        module_name = f"drivers.{py_file.stem}"
        if module_name in sys.modules:
            continue
        if importlib.util.find_spec(module_name) is None:
            continue
        try:
            importlib.import_module(module_name)
        except Exception:
            pass


def cmd_convert(src: str, dst: str) -> None:
    src_path = Path(src)
    dst_path = Path(dst)

    if not src_path.is_file():
        logger.error(f"Source file not found: {src_path}")
        sys.exit(1)

    try:
        data = config_io.load_config(src_path)
    except Exception:
        logger.opt(exception=True).critical(f"Error reading {src_path}")
        sys.exit(1)

    try:
        config_io.save_config(data, dst_path)
    except Exception:
        logger.opt(exception=True).critical(f"Error reading {dst_path}")
        sys.exit(1)

    print(f"Converted {src_path} → {dst_path}")


def cmd_validate(args: argparse.Namespace) -> None:
    """Validate config / rules files for syntax correctness."""
    data_path = Path(args.data_path or u.get_data_path())
    manual_config = args.config is not None
    manual_rules = args.rules is not None
    any_manual = manual_config or manual_rules

    if manual_config:
        config_path = Path(args.config)
        if not config_path.is_file():
            print(f"Config file not found: {config_path}", file=sys.stderr)
            sys.exit(2)
        validate_config = True
    elif not any_manual:
        config_path = config_io.find_config(data_path)
        validate_config = config_path is not None
    else:
        validate_config = False

    if manual_rules:
        rules_path = Path(args.rules)
        if not rules_path.is_file():
            print(f"Rules file not found: {rules_path}", file=sys.stderr)
            sys.exit(2)
        validate_rules = True
    elif not any_manual:
        rules_path = config_io.find_rules(data_path)
        validate_rules = rules_path is not None
    else:
        validate_rules = False

    has_errors = False

    if validate_config:
        assert config_path is not None
        print(f"Validating config: {config_path}", flush=True)
        try:
            raw = config_io.load_config(config_path)
        except Exception as exc:
            print(f"Failed to parse config file: {exc}", file=sys.stderr)
            sys.exit(1)

        global_raw = raw.get("global", {})
        try:
            GlobalConfig.model_validate(global_raw)
            print("  global: OK")
        except ValidationError as exc:
            print(f"  global: FAILED\n{exc}", file=sys.stderr)
            has_errors = True

        _discover_all_driver_modules()
        from drivers.registry import all_drivers

        registry = all_drivers()
        for platform, (config_cls, _) in registry.items():
            for inst_id, inst_raw in raw.get(platform, {}).items():
                try:
                    config_cls.model_validate(inst_raw)
                    print(f"  {platform}.{inst_id}: OK")
                except ValidationError as exc:
                    print(f"  {platform}.{inst_id}: FAILED\n{exc}", file=sys.stderr)
                    has_errors = True

    if validate_rules:
        assert rules_path is not None
        print(f"Validating rules: {rules_path}", flush=True)
        try:
            data = config_io.load_config(rules_path)
        except Exception as exc:
            print(f"Failed to parse rules file: {exc}", file=sys.stderr)
            sys.exit(1)

        try:
            RulesFile.model_validate(data)
            print("  rules: OK")
        except ValidationError as exc:
            print(f"  rules: FAILED\n{exc}", file=sys.stderr)
            has_errors = True

    if has_errors:
        sys.exit(1)

    print("Validation passed.")
    sys.exit(0)


async def main():
    try:
        version = _load_project_version()
    except Exception:
        logger.opt(exception=True).critical("Startup aborted: failed to load version")
        return

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

    # Load global configuration
    global_config = raw.get("global", {})
    bridge.strict_echo_match = global_config.get("strict_echo_match", False)
    bridge.fuzzy_mention_match = global_config.get("fuzzy_mention_match", False)

    try:
        validated_global = GlobalConfig.model_validate(global_config)
    except ValidationError as exc:
        logger.opt(exception=exc).critical("Global configuration error")
        return

    # Logging configuration
    log.set_show_source(validated_global.log.show_source)
    log.set_console_level(validated_global.log.level)
    log.set_log_dir(validated_global.log.dir)
    log.set_log_rotation(
        rotation_size=validated_global.log.rotation_size,
        retention_days=validated_global.log.retention_days,
        compression=validated_global.log.compression,
        file_level=validated_global.log.file_level,
    )
    bridge.command_prefix = validated_global.command_prefix

    try:
        init_db()
        logger.info(
            f"Database initialized at startup with db_version target {db_target_version()}"
        )
    except Exception:
        logger.opt(exception=True).critical(
            "Startup aborted: database initialization failed"
        )
        return

    # ------------------------------------------------------------------
    # Set up plugin infrastructure
    # ------------------------------------------------------------------
    event_bus = EventBus()
    middleware = MiddlewareChain()
    bridge.set_middleware(middleware)
    bridge.set_event_bus(event_bus)

    # Discover and import driver modules (built-in, entrypoints, local, external)
    plugin_cfg = validated_global.plugins
    drivers_cfg = plugin_cfg.drivers

    if drivers_cfg.enabled:
        enabled_platforms = list(drivers_cfg.enabled)
    else:
        enabled_platforms = [key for key in raw if key != "global"]

    for ext_name in drivers_cfg.external:
        if ext_name not in enabled_platforms:
            enabled_platforms.append(ext_name)

    load_all_drivers(enabled_platforms, drivers_cfg, plugin_cfg.paths or None)
    from drivers.registry import all_drivers

    logger.info("NextBridge starting...")

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

    http_server = HttpServerManager(
        host=validated_global.http.host,
        port=validated_global.http.port,
        root_path=validated_global.http.root_path,
        log_level=validated_global.http.log_level,
        start_without_mounts=validated_global.http.enable == "true",
        version=version,
    )

    # ------------------------------------------------------------------
    # Create driver context and manager
    # ------------------------------------------------------------------
    ctx = DriverContext(
        bridge=bridge,
        http_server=http_server,
        event_bus=event_bus,
        middleware=middleware,
        version=version,
        config_path=config_path,
    )

    driver_manager = DriverManager(
        event_bus,
        auto_restart=plugin_cfg.auto_restart,
        max_restart_attempts=plugin_cfg.max_restart_attempts,
        health_check_interval=plugin_cfg.health_check_interval,
    )

    logger.info(f"========== NextBridge v{version} Starting ==========")

    for platform, (_, driver_cls) in registry.items():
        for inst_id, cfg in validated.get(platform, {}).items():
            drv = driver_cls(inst_id, cfg, ctx)
            drv.attach_http_server(http_server)
            await driver_manager.register_and_start(platform, inst_id, drv, cfg)
            logger.info(f"Registered driver: {platform}/{inst_id}")

    has_drivers = bool(driver_manager.drivers)
    if not has_drivers and validated_global.http.enable != "true":
        logger.error("No drivers configured — nothing to do, exiting.")
        return
    if not has_drivers and validated_global.http.enable == "true":
        logger.warning(
            "No drivers configured — starting HTTP server due to http.enable=true"
        )

    # Start health monitoring
    await driver_manager.start_health_monitor()

    # Let drivers perform startup and register webhook sub-apps.
    await asyncio.sleep(0)

    all_tasks: list[asyncio.Task] = []
    http_enable = validated_global.http.enable
    if http_enable == "false":
        if http_server.has_mounts():
            logger.warning(
                "HTTP server is disabled by http.enable=false while drivers mounted "
                "webhook sub-apps; inbound webhook features are unavailable"
            )
        logger.info("Shared HTTP server disabled by configuration (http.enable=false)")
    elif http_server.should_start():
        admin_cfg = plugin_cfg.admin
        if admin_cfg.enable:
            if not admin_cfg.password:
                logger.critical(
                    "Admin API is enabled but no password is set "
                    "(global.plugins.admin.password). Refusing to start."
                )
                return
            http_server.set_driver_manager(driver_manager, password=admin_cfg.password)
        http_task = asyncio.create_task(http_server.run(), name="http/shared")
        all_tasks.append(http_task)
    else:
        logger.info("No HTTP sub-app mounted; shared HTTP server disabled")

    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        logger.info("NextBridge shutting down...")
    finally:
        await driver_manager.stop_all()

        for task in all_tasks:
            if not task.done():
                task.cancel()
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)

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

    valid = subparsers.add_parser(
        "validate",
        help="Validate config and rules files for syntax correctness",
    )
    valid.add_argument(
        "--config", "-c", help="Path to config file (optional, overrides default)"
    )
    valid.add_argument(
        "--rules", "-r", help="Path to rules file (optional, overrides default)"
    )
    valid.add_argument(
        "--data-path",
        "-d",
        help="Data directory for default discovery (defaults to NEXTBRIDGE_DATA_PATH or data/)",
    )

    # Discover CLI hooks from all driver modules (built-in + plugins).
    # This imports every driver .py but only to pick up register_cli() calls;
    # the full driver startup happens later in main().
    _discover_all_driver_modules()
    from drivers.registry import all_cli_hooks

    for hook in all_cli_hooks():
        try:
            hook(subparsers)
        except Exception:
            pass

    args = parser.parse_args()

    if args.command == "convert":
        cmd_convert(args.src, args.dst)
        sys.exit(0)

    if args.command == "validate":
        cmd_validate(args)
        sys.exit(0)

    # Dispatch plugin CLI subcommands.
    # Drivers register handlers by attaching a _cli_handler attribute
    # to the subparser action via set_defaults().
    handler = getattr(args, "cli_handler", None)
    if handler is not None:
        handler(args)
        sys.exit(0)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        # close all sessions to avoid connection leaks
        asyncio.run(close_all_sessions())
