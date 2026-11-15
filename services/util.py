import os
import re
import unicodedata
from collections import OrderedDict
from typing import Any, Generic, TypeVar
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SENSITIVE_QUERY_KEYS = {
    "access_token",
    "token",
    "key",
    "secret",
    "password",
    "sig",
    "signature",
    "auth",
}
_BOT_TOKEN_PATH_RE = re.compile(r"(/bot)([^/]+)", re.IGNORECASE)

# Unicode general categories that render as nothing (or as control behaviour)
# and therefore must never be bridged as part of a display name:
#   Cc = control, Cf = format (zero-width joiner/space, bidi overrides, ...),
#   Cs = surrogate, Co = private use, Cn = unassigned,
#   Zl = line separator, Zp = paragraph separator.
# Note: Zs (spaces) is intentionally kept — names may legitimately contain a
# normal space.
_INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})

# Variation selectors are category Mn (combining marks) yet render as nothing on
# their own — they only modify the preceding glyph — so they are dropped too.
_INVISIBLE_RANGES = (
    (0xFE00, 0xFE0F),  # Variation Selectors
    (0xE0100, 0xE01EF),  # Variation Selectors Supplement
)


def _is_invisible_char(ch: str) -> bool:
    if unicodedata.category(ch) in _INVISIBLE_CATEGORIES:
        return True
    code = ord(ch)
    return any(start <= code <= end for start, end in _INVISIBLE_RANGES)


K = TypeVar("K")
V = TypeVar("V")


class LRUDict(OrderedDict[K, V], Generic[K, V]):
    """OrderedDict-based LRU cache with fixed max capacity."""

    def __init__(self, maxsize: int = 1000, *args, **kwargs):
        self.maxsize = maxsize
        super().__init__(*args, **kwargs)

    def __getitem__(self, key: K) -> V:
        value = super().__getitem__(key)
        self.move_to_end(key)
        return value

    def get(self, key: object, default: Any = None, /) -> Any:
        if key in self:
            typed_key: Any = key
            self.move_to_end(typed_key)
            return super().__getitem__(typed_key)
        return default

    def __setitem__(self, key: K, value: V) -> None:
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        if len(self) > self.maxsize:
            self.popitem(last=False)


def get_data_path():
    path = get_env("NEXTBRIDGE_DATA_PATH") or get_env("nextbridge_data_path")
    return path.strip() if path else "data"


def get_env(env: str):
    return os.environ.get(env)


def strip_invisible_chars(value: object, *, prefix: str = "") -> str:
    """Remove non-rendering Unicode characters from a display string.

    Drops control, format (zero-width spaces/joiners, bidi overrides),
    surrogate, private-use, unassigned, line/paragraph separator characters and
    variation selectors. Normal spaces and all visible characters are preserved.
    Returns the input unchanged when it contains no such characters, and returns
    an empty string for non-string values so callers can pass ``None``/ints
    safely.
    """
    if not isinstance(value, str):
        return ""
    if not value:
        return value
    cleaned = "".join(ch for ch in value if not _is_invisible_char(ch))
    if cleaned == value:
        return value
    return f"{prefix}{cleaned}" if prefix else cleaned


def strip_invisible_chars_in_obj(obj: Any, *, prefix: str = "") -> Any:
    """Recursively apply :func:`strip_invisible_chars` to strings/keys in *obj*."""
    if isinstance(obj, str):
        return strip_invisible_chars(obj, prefix=prefix)
    if isinstance(obj, dict):
        return {
            (
                strip_invisible_chars_in_obj(k, prefix=prefix)
                if isinstance(k, str)
                else k
            ): strip_invisible_chars_in_obj(v, prefix=prefix)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [strip_invisible_chars_in_obj(item, prefix=prefix) for item in obj]
    if isinstance(obj, tuple):
        return tuple(strip_invisible_chars_in_obj(item, prefix=prefix) for item in obj)
    return obj


def mask_url_credentials(url: str) -> str:
    """Mask userinfo and sensitive query params in *url* for safe logging."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "***"
    if parts.username or parts.password:
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        parts = parts._replace(netloc=f"***:***@{host}")
    if parts.query:
        masked = urlencode(
            [
                (k, "***" if k.lower() in _SENSITIVE_QUERY_KEYS else v)
                for k, v in parse_qsl(parts.query, keep_blank_values=True)
            ]
        )
        parts = parts._replace(query=masked)
    path = parts.path
    if "/bot" in path.lower():
        path = _BOT_TOKEN_PATH_RE.sub(r"\1***", path)
        parts = parts._replace(path=path)
    return urlunsplit(parts)
