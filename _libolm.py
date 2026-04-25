"""Minimal `_libolm` shim for mautrix when running with fresholm.

fresholm provides a python-olm compatible `olm` module, but does not ship the
CFFI `_libolm` extension. mautrix imports `_libolm` for an optional debug
method. This shim keeps that import working without requiring libolm.
"""


class _DummyFFI:
    """Placeholder object to satisfy mautrix import-time expectations."""


class _DummyLib:
    """Placeholder object; no `olm_session_describe` means graceful fallback."""


ffi = _DummyFFI()
lib = _DummyLib()
