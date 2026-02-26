from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict


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


class GlobalConfig(BaseModel):
    """Global configuration options that apply to all drivers unless overridden."""
    
    proxy: str = ""
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
