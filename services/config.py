import json
import hashlib
from pathlib import Path
from typing import Any

import services.util as u
import services.logger as log
import services.config_io as config_io
from services.config_schema import UNSET

logger = log.get_logger()

_config_cache = None
_config_path: Path | None = None


def _strip_msg_blocks(obj):
    """Return a copy of *obj* with every ``msg`` block removed recursively."""
    if isinstance(obj, dict):
        return {k: _strip_msg_blocks(v) for k, v in obj.items() if k != "msg"}
    if isinstance(obj, list):
        return [_strip_msg_blocks(item) for item in obj]
    return obj


def stable_rule_hash(rule: dict) -> str:
    """Build a stable hash for a rule, ignoring ``id`` and all ``msg`` blocks."""
    sanitized = _strip_msg_blocks(rule)
    if isinstance(sanitized, dict):
        sanitized.pop("id", None)
    raw = json.dumps(
        sanitized, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def resolve_rule_id(rule: dict) -> str:
    """Resolve rule id from explicit config, or fallback to stable rule hash."""
    configured = rule.get("id")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return stable_rule_hash(rule)


def normalize_rules_with_ids(rules: list[dict]) -> list[dict]:
    """Normalize rules so each rule has a non-empty id."""
    normalized: list[dict] = []
    seen_ids: dict[str, int] = {}
    for idx, rule in enumerate(rules):
        if not isinstance(rule, dict):
            logger.warning(f"Skip invalid rule at index {idx}: not an object")
            continue

        base_id = resolve_rule_id(rule)
        count = seen_ids.get(base_id, 0) + 1
        seen_ids[base_id] = count
        resolved_id = base_id if count == 1 else f"{base_id}#{count}"

        if count > 1:
            logger.warning(
                f"Duplicate rule id '{base_id}' detected, auto-adjust to '{resolved_id}'"
            )

        rule_with_id = dict(rule)
        rule_with_id["id"] = resolved_id
        normalized.append(rule_with_id)

    return normalized


def load_rules_with_ids() -> tuple[list[dict], Path | None]:
    """Load rules file and normalize every rule with a stable id."""
    rules_path = config_io.find_rules(Path(u.get_data_path()))
    if rules_path is None:
        return [], None

    data = config_io.load_config(rules_path)
    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list):
        logger.warning("Invalid rules format: 'rules' must be an array")
        return [], rules_path

    return normalize_rules_with_ids(raw_rules), rules_path


def _load_config():
    """Load the config file into the in-memory cache."""
    global _config_cache, _config_path

    if _config_cache is not None:
        return _config_cache

    found = config_io.find_config(Path(u.get_data_path()))
    if found is None:
        raise FileNotFoundError(f"No config file found in: {u.get_data_path()}")

    _config_path = found
    _config_cache = config_io.load_config(found)
    return _config_cache


def get(key: str, default: Any = None) -> Any:
    """
    Get a config value. Supports dot-notation for nested keys, e.g. ``get("database.host")``.
    """
    try:
        config = _load_config()
    except Exception as e:
        logger.warning(f"Failed to load config file! Error: {e}")
        return default

    keys = key.split(".")
    value = config
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default
    return value


def set(key: str, value):
    """
    Set a config value and write it back to the file.

    :param key: Config key, supports dot-notation (e.g. ``"a.b.c"``).
    :param value: Value to set.
    """
    global _config_cache, _config_path
    try:
        if _config_cache is None:
            config = _load_config()
        else:
            config = _config_cache
    except Exception:
        config = {}

    keys = key.split(".")
    d = config
    for k in keys[:-1]:
        if k not in d or not isinstance(d[k], dict):
            d[k] = {}
        d = d[k]
    d[keys[-1]] = value

    path = _config_path or (Path(u.get_data_path()) / "config.json")
    try:
        config_io.save_config(config, path)
        _config_cache = config
    except Exception as e:
        raise RuntimeError(f"Save config failed: {e}")


def get_proxy(
    instance: str | None = UNSET, globally: str | None = get("global.proxy", UNSET)
) -> str | None:
    if not instance == UNSET:
        return instance or None
    elif not globally == UNSET:
        return globally or None
    else:
        return None
