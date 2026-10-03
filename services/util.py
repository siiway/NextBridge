import os
from collections import OrderedDict
from typing import Any, Generic, TypeVar
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SENSITIVE_QUERY_KEYS = {"access_token", "token", "key", "secret", "password"}

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
    return urlunsplit(parts)
