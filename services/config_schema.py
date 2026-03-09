from __future__ import annotations

from typing import Annotated
from os import environ

from pydantic import BaseModel, BeforeValidator, ConfigDict

from services.logger import logger

# ---------------------------------------------------------------------------
# Reusable bool coercion: "true" / "1" / "yes" → True
# ---------------------------------------------------------------------------


def _coerce_bool(v: object) -> object:
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes")
    return v


CoercedBool = Annotated[bool, BeforeValidator(_coerce_bool)]


# ---------------------------------------------------------------------------
# Global configuration
# ---------------------------------------------------------------------------

def _get_proxy_from_env(v: str) -> str:
    if v.lower() in ['disabled', 'disable']:
        logger.debug(f'Global proxy disabled manually')
        return ''
    
    elif v:
        logger.debug(f"Using global proxy from config file: {v}")
        return v

    for env_var in ['http_proxy', 'https_proxy', 'all_proxy']:
        env_value = environ.get(env_var) or environ.get(env_var.upper())
        if env_value:
            logger.debug(f"Using global proxy from environ variable {env_var}: {env_value}")
            return env_value

    logger.debug(f"No global proxy configuration found")
    return ""


class GlobalConfig(BaseModel):
    """Global configuration options that apply to all drivers unless overridden."""
    
    proxy: Annotated[str, BeforeValidator(_get_proxy_from_env)] = ""
    """Global proxy URL for all drivers that support proxy configuration.
    Individual driver proxy settings will override this global setting."""


# ---------------------------------------------------------------------------
# Base for all driver config blocks — unknown keys are a validation error
# ---------------------------------------------------------------------------


class _DriverConfig(BaseModel):
    """Shared base for every per-driver config model.

    Sets ``extra="forbid"`` so typos in the config file are caught at startup
    rather than silently ignored.
    """

    model_config = ConfigDict(extra="forbid")
