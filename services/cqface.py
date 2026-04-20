from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from services.util import get_data_path
import services.logger as log

logger = log.get_logger()
_CQFACE_RE = re.compile(r":cqface(\d+):")


@lru_cache(maxsize=1)
def _load_cqface_map() -> dict[str, str]:
    candidates = [
        Path(get_data_path()) / "cqface-map.yaml",
        Path(__file__).resolve().parent.parent / "db" / "cqface-map.yaml",
    ]
    for path in candidates:
        if not path.is_file():
            continue

        try:
            with path.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except Exception:
            logger.opt(exception=True).warning("Load cqface map failed!")
            return {}

        if not isinstance(raw, dict):
            return {}

        mapping: dict[str, str] = {}
        for face_id, emoji in raw.items():
            if emoji is None:
                continue
            mapping[str(face_id)] = str(emoji)
        return mapping

    return {}


def resolve_cqface(face_id: str) -> str:
    mapping = _load_cqface_map()
    return mapping.get(face_id, f":cqface{face_id}:")


def replace_cqface_tokens(text: str) -> str:
    if ":cqface" not in text:
        return text
    return _CQFACE_RE.sub(lambda m: resolve_cqface(m.group(1)), text)


def replace_cqface_tokens_in_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return replace_cqface_tokens(obj)
    if isinstance(obj, dict):
        return {k: replace_cqface_tokens_in_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [replace_cqface_tokens_in_obj(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(replace_cqface_tokens_in_obj(v) for v in obj)
    return obj
