"""Unified config file I/O supporting JSON, YAML, and TOML.

Format is always inferred from the file extension:
  .json        → JSON
  .yaml / .yml → YAML  (requires pyyaml)
  .toml        → TOML  (read: stdlib tomllib; write: tomli-w)

Writes are atomic (temp file + fsync + ``os.replace``).  YAML additionally
supports a round-trip mode that preserves comments and anchors via
``ruamel.yaml``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import tomllib
from pathlib import Path
from typing import Any

_YAML_EXTS = {".yaml", ".yml"}
_TOML_EXTS = {".toml"}

_CONFIG_NAMES = ["config.json", "config.yaml", "config.yml", "config.toml"]
_RULES_NAMES = ["rules.json", "rules.yaml", "rules.yml", "rules.toml"]


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


def _serialize(data: dict[str, Any], ext: str) -> bytes:
    """Serialize *data* to bytes according to the file extension."""
    if ext in _YAML_EXTS:
        import yaml  # pyyaml

        return yaml.dump(
            data, allow_unicode=True, sort_keys=False, default_flow_style=False
        ).encode("utf-8")
    if ext in _TOML_EXTS:
        import tomli_w

        return tomli_w.dumps(data).encode("utf-8")
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    """Write *payload* to *path* atomically (temp file + fsync + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        dfd = os.open(str(path.parent), os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def backup_file(path: Path) -> Path | None:
    """Copy *path* to ``<name>.bak`` before a write; returns the backup path."""
    if not path.is_file():
        return None
    bak = path.with_name(path.name + ".bak")
    shutil.copy2(path, bak)
    return bak


def file_sha256(path: Path) -> str | None:
    """Return the SHA-256 hex digest of *path*, or ``None`` if missing."""
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def save_config(data: dict[str, Any], path: Path, *, backup: bool = False) -> None:
    """Atomically save *data* to *path*; format inferred from the extension."""
    if backup:
        backup_file(path)
    _atomic_write(path, _serialize(data, path.suffix.lower()))


def load_yaml_roundtrip(path: Path):
    """Load YAML with comments/anchors preserved (ruamel round-trip)."""
    from ruamel.yaml import YAML

    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    with open(path, "r", encoding="utf-8") as f:
        return yaml.load(f)


def dump_yaml_roundtrip(data: Any, path: Path, *, backup: bool = True) -> None:
    """Atomically dump round-trip YAML, preserving comments and anchors."""
    import io

    from ruamel.yaml import YAML

    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.allow_unicode = True
    buf = io.StringIO()
    yaml.dump(data, buf)
    if backup:
        backup_file(path)
    _atomic_write(path, buf.getvalue().encode("utf-8"))
