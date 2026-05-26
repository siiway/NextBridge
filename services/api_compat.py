"""API version detection for external driver plugins.

Built-in drivers are transparently handled by ``BaseDriver.__init__``
(which accepts both ``Bridge`` and ``DriverContext``).  This module is
only needed when loading third-party plugins that may declare an older
API version.
"""

from __future__ import annotations

import inspect

import services.logger as log

logger = log.get_logger("api_compat")


def detect_api_version(driver_cls: type) -> int:
    meta = getattr(driver_cls, "meta", None)
    if meta and hasattr(meta, "api_version"):
        return int(meta.api_version)

    version = getattr(driver_cls, "DRIVER_API_VERSION", None)
    if version is not None:
        return int(version)

    try:
        sig = inspect.signature(driver_cls.__init__)
        params = list(sig.parameters.keys())
        if "ctx" in params or "ctx_or_bridge" in params:
            return 2
        if "bridge" in params:
            return 1
    except (ValueError, TypeError):
        pass

    return 1
