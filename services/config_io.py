"""Unified config file I/O supporting YAML, TOML, and JSON5.

Format is always inferred from the file extension:
  .yaml / .yml → YAML  (requires pyyaml)
  .toml        → TOML  (read: stdlib tomllib; write: tomli-w)
  .json / .jsonc / .json5 → JSON5 (requires pyjson5)

Search priority (first found wins): yaml → toml → json
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

_YAML_EXTS = {".yaml", ".yml"}
_TOML_EXTS = {".toml"}
_JSON_EXTS = {".json", ".jsonc", ".json5"}

_CONFIG_NAMES = [
    "config.yaml",
    "config.yml",
    "config.toml",
    "config.json",
    "config.jsonc",
    "config.json5",
]
_RULES_NAMES = [
    "rules.yaml",
    "rules.yml",
    "rules.toml",
    "rules.json",
    "rules.jsonc",
    "rules.json5",
]


def find_config(directory: Path) -> Path | None:
    """Return the first existing config file found in *directory*."""
    for name in _CONFIG_NAMES:
        p = directory / name
        if p.is_file():
            return p
    return None


def find_rules(directory: Path) -> Path | None:
    """Return the first existing rules file found in *directory*."""
    for name in _RULES_NAMES:
        p = directory / name
        if p.is_file():
            return p
    return None


def _load_json5(path: Path) -> dict[str, Any]:
    """Load a JSON/JSONC/JSON5 file using pyjson5."""
    import pyjson5

    return pyjson5.loads(path.read_text(encoding="utf-8"))


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
    # Default: JSON/JSONC/JSON5
    return _load_json5(path)


def save_config(data: dict[str, Any], path: Path) -> None:
    """Save *data* to *path*; format is inferred from the file extension."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix.lower()
    if ext in _YAML_EXTS:
        import yaml  # pyyaml

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(
                data, f, allow_unicode=True, sort_keys=False, default_flow_style=False
            )
        return
    if ext in _TOML_EXTS:
        import tomli_w

        with open(path, "wb") as f:
            tomli_w.dump(data, f)
        return
    # Default: JSON5 (write standard JSON, compatible with JSON5 parsers)
    import json

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
