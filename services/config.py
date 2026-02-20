from pathlib import Path

import services.util as u
import services.logger as log
import services.config_io as config_io

l = log.get_logger()

_config_cache = None
_config_path: Path | None = None


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


def get(key: str, default=None):
    """
    Get a config value. Supports dot-notation for nested keys, e.g. ``get("database.host")``.
    """
    try:
        config = _load_config()
    except Exception as e:
        l.warning(f"Failed to load config file! Error: {e}")
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
