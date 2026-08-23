import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SENSITIVE_QUERY_KEYS = {"access_token", "token", "key", "secret", "password"}


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
