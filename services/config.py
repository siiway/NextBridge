# services/config.py

import json
import os
from pathlib import Path

import services.util as u
import services.logger as log

l = log.get_logger()

data_path = u.get_data_path()
config_file_path = Path(data_path) / "config.json"

_config_cache = None

def _load_config():
    """内部函数：加载配置文件到内存缓存"""
    global _config_cache

    if _config_cache is not None:
        return _config_cache

    if not config_file_path.is_file():
        raise FileNotFoundError(f"File not found: {config_file_path}")

    try:
        with open(config_file_path, 'r', encoding='utf-8') as f:
            _config_cache = json.load(f)
        return _config_cache
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON decode error: {config_file_path}, Error: {e}")
    except Exception as e:
        raise RuntimeError(f"Read config failed: {e}")

def get(key: str, default=None):
    """
    获取配置项的值。

    支持嵌套键，用点号 '.' 分隔，例如:
        get("database.host")
        get("app.debug")

    :param key: 配置项的键（支持点号分隔的嵌套键）
    :param default: 如果键不存在，返回的默认值
    :return: 配置值或默认值
    """
    global _config_cache

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
            return default  # 键不存在或路径中断
    return value


def set(key: str, value):
    """
    （可选）设置配置项并写回文件（谨慎使用）

    :param key: 配置键（支持嵌套，如 "a.b.c"）
    :param value: 要设置的值
    """
    global _config_cache
    try:
        if _config_cache is None:
            config = _load_config()  # 触发加载
        else:
            config = _config_cache
    except:
        config = {}

    keys = key.split(".")
    d = config
    for k in keys[:-1]:
        if k not in d or not isinstance(d[k], dict):
            d[k] = {}
        d = d[k]
    d[keys[-1]] = value

    # 写回文件
    try:
        config_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_file_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        _config_cache = config  # 更新缓存
    except Exception as e:
        raise RuntimeError(f"Save config failed: {e}")