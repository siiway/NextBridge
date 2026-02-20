"""Unified config file I/O supporting JSON, YAML, and TOML.

Format is always inferred from the file extension:
  .json        → JSON
  .yaml / .yml → YAML  (requires pyyaml)
  .toml        → TOML  (read: stdlib tomllib; write: tomli-w)
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

_YAML_EXTS = {".yaml", ".yml"}
_TOML_EXTS = {".toml"}

_CONFIG_NAMES = ["config.json", "config.yaml", "config.yml", "config.toml"]


def find_config(directory: Path) -> Path | None:
    """Return the first existing config file found in *directory*."""
    for name in _CONFIG_NAMES:
        p = directory / name
        if p.is_file():
            return p
    return None


def load_config(path: Path) -> dict[str, Any]:
    """Load a config file; format is inferred from the file extension."""
    ext = path.suffix.lower()
    if ext in _YAML_EXTS:
        import yaml  # pyyaml
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    if ext in _TOML_EXTS:
        with open(path, "rb") as f:
            return tomllib.load(f)
    # Default: JSON
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(data: dict[str, Any], path: Path) -> None:
    """Save *data* to *path*; format is inferred from the file extension."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix.lower()
    if ext in _YAML_EXTS:
        import yaml  # pyyaml
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        return
    if ext in _TOML_EXTS:
        import tomli_w
        with open(path, "wb") as f:
            tomli_w.dump(data, f)
        return
    # Default: JSON
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
