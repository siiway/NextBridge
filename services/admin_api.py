from __future__ import annotations

import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any

import services.audit as audit
import services.config_io as config_io
import services.logger as log
from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from prometheus_client import CONTENT_TYPE_LATEST
from services.reload import HOT_RELOAD_GLOBAL_KEYS, ReloadEngine, ReloadError

if TYPE_CHECKING:
    from plugins.manager import PluginManager
    from services.bridge import Bridge
    from services.driver_manager import DriverManager
    from services.metrics import MetricsCollector

logger = log.get_logger("admin")

_JSON_HEADERS = {"Cache-Control": "no-store"}

_SENSITIVE_KEY_HINTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "credential",
)


class AdminError(Exception):
    """Raised by admin routes to produce a structured error response."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 400,
        code: str = "admin_error",
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details


def _safe(value: Any) -> Any:
    """Best-effort JSON-safe conversion (pydantic errors contain exotic objs)."""
    import json

    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return str(value)


def _ok(data: Any = None) -> JSONResponse:
    return JSONResponse({"ok": True, "data": data}, headers=_JSON_HEADERS)


def _err(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    return JSONResponse(
        {
            "ok": False,
            "error": {
                "code": code,
                "message": message,
                "details": _safe(details) if details is not None else None,
            },
        },
        status_code=status,
        headers=_JSON_HEADERS,
    )


def _client_ip(request: Request) -> str:
    if request.client is None:
        return ""
    return request.client.host or ""


def _redact(obj: Any, sensitive: frozenset[str]) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            lowered = str(key).lower()
            if any(hint in lowered for hint in _SENSITIVE_KEY_HINTS):
                out[key] = "***"
            else:
                out[key] = _redact(value, sensitive)
        return out
    if isinstance(obj, list):
        return [_redact(item, sensitive) for item in obj]
    if isinstance(obj, str) and obj in sensitive:
        return "***"
    return obj


def _write_structured(data: dict, path: Path, *, backup: bool = True) -> None:
    if path.suffix.lower() in {".yaml", ".yml"}:
        config_io.dump_yaml_roundtrip(data, path, backup=backup)
    else:
        config_io.save_config(data, path, backup=backup)


def _status_for_reload(code: str) -> int:
    if code in {
        "config_not_found",
        "config_parse_error",
        "rules_parse_error",
        "invalid_rules",
        "invalid_config",
        "invalid_driver_config",
    }:
        return 400
    return 500


def build_admin_app(
    *,
    version: str,
    debug: bool = False,
    bridge: Bridge | None = None,
    driver_manager: DriverManager | None = None,
    plugin_manager: PluginManager | None = None,
    reload_engine: ReloadEngine | None = None,
    metrics: MetricsCollector | None = None,
    admin_enabled: bool = False,
    admin_user: str = "",
    admin_password: str = "",
) -> FastAPI:
    """Build the ``/_nextbridge`` API sub-app.

    The public health route is always registered.  All other routes are only
    registered when *admin_enabled* is true, so a disabled admin API is
    entirely absent (fail-closed) rather than silently unauthenticated.
    """
    app = FastAPI()
    security = HTTPBasic(auto_error=False)

    @app.exception_handler(AdminError)
    async def _on_admin_error(_request: Request, exc: AdminError) -> JSONResponse:
        return _err(exc.status, exc.code, str(exc), exc.details)

    @app.exception_handler(ReloadError)
    async def _on_reload_error(_request: Request, exc: ReloadError) -> JSONResponse:
        return _err(_status_for_reload(exc.code), exc.code, str(exc), exc.details)

    @app.get("/health")
    async def _health() -> JSONResponse:
        payload: dict[str, object] = {"status": "ok", "version": version}
        if debug and driver_manager is not None:
            payload["drivers"] = list(driver_manager.drivers)
        return JSONResponse(payload, headers=_JSON_HEADERS)

    if not admin_enabled:
        return app

    def _require_auth(
        request: Request,
        credentials: HTTPBasicCredentials | None = Depends(security),
    ) -> str:
        if credentials is None:
            raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
        user_ok = secrets.compare_digest(credentials.username, admin_user)
        pass_ok = secrets.compare_digest(credentials.password, admin_password)
        if not (user_ok and pass_ok):
            audit.record(
                "auth.failure",
                actor=credentials.username,
                source_ip=_client_ip(request),
                result="fail",
            )
            raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
        return credentials.username

    def _engine() -> ReloadEngine:
        if reload_engine is None:
            raise AdminError(
                "Reload engine not available",
                status=503,
                code="reload_engine_unavailable",
            )
        return reload_engine

    def _load_config_roundtrip(engine: ReloadEngine) -> dict:
        path = engine.config_path
        if path is not None and path.suffix.lower() in {".yaml", ".yml"}:
            try:
                data = config_io.load_yaml_roundtrip(path)
            except Exception as exc:
                raise AdminError(
                    f"Failed to read config file: {exc}",
                    code="config_parse_error",
                    details=str(exc),
                ) from exc
            if not isinstance(data, dict):
                raise AdminError(
                    "Config file must contain a mapping",
                    code="invalid_config",
                )
            return data
        return engine.read_config_file()

    def _load_rules() -> tuple[dict, Path]:
        data, path = _engine().read_rules_file()
        if path is None:
            raise AdminError(
                "No rules file configured",
                status=404,
                code="rules_not_found",
            )
        if path.suffix.lower() in {".yaml", ".yml"}:
            try:
                data = config_io.load_yaml_roundtrip(path)
            except Exception as exc:
                raise AdminError(
                    f"Failed to read rules file: {exc}",
                    code="rules_parse_error",
                    details=str(exc),
                ) from exc
        if not isinstance(data, dict):
            data = {}
        data.setdefault("rules", [])
        return data, path

    def _conflict_guard(path: Path, expected: str | None, force: bool) -> None:
        if force or not expected:
            return
        current = config_io.file_sha256(path)
        if current != expected:
            raise AdminError(
                "File changed on disk; re-read and retry or pass force=true",
                status=409,
                code="conflict",
                details={"current_sha256": current, "expected_sha256": expected},
            )

    async def _commit_rules(
        data: dict,
        path: Path,
        *,
        event: str,
        actor: str,
        request: Request,
        target: str = "",
        before: Any = None,
    ) -> JSONResponse:
        engine = _engine()
        async with engine.lock:
            rules = engine.parse_rules(data)
            data["rules"] = rules
            backup_path = config_io.backup_file(path)
            _write_structured(data, path, backup=False)
            engine.apply_rules(rules)
        audit.record(
            event,
            actor=actor,
            source_ip=_client_ip(request),
            target=target,
            before=before,
            after={"rules": len(rules)},
            result="ok",
        )
        return _ok(
            {
                "rules": len(rules),
                "backup": str(backup_path) if backup_path else None,
                "sha256": config_io.file_sha256(path),
            }
        )

    # ------------------------------------------------------------------
    # Read endpoints
    # ------------------------------------------------------------------
    @app.get("/drivers")
    async def _drivers(_actor: str = Depends(_require_auth)) -> JSONResponse:
        if driver_manager is None:
            raise AdminError(
                "Driver manager not available",
                status=503,
                code="driver_manager_unavailable",
            )
        return _ok({"drivers": driver_manager.get_status()})

    @app.get("/plugins")
    async def _plugins(_actor: str = Depends(_require_auth)) -> JSONResponse:
        if plugin_manager is None:
            raise AdminError(
                "Plugin manager not available",
                status=503,
                code="plugin_manager_unavailable",
            )
        return _ok({"plugins": plugin_manager.get_status()})

    @app.get("/metrics")
    async def _metrics(_actor: str = Depends(_require_auth)) -> Response:
        if metrics is None:
            raise AdminError(
                "Metrics not available",
                status=503,
                code="metrics_unavailable",
            )
        return Response(content=metrics.render(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/rules")
    async def _get_rules(_actor: str = Depends(_require_auth)) -> JSONResponse:
        data, path = _engine().read_rules_file()
        rules = data.get("rules", []) if isinstance(data, dict) else []
        return _ok(
            {
                "rules": rules,
                "path": str(path) if path else None,
                "sha256": config_io.file_sha256(path) if path else None,
            }
        )

    @app.get("/config")
    async def _get_config(_actor: str = Depends(_require_auth)) -> JSONResponse:
        engine = _engine()
        raw = engine.read_config_file()
        sensitive = frozenset(getattr(bridge, "_sensitive", frozenset()))
        return _ok(
            {
                "config": _redact(raw, sensitive),
                "path": str(engine.config_path),
                "sha256": config_io.file_sha256(engine.config_path),
            }
        )

    # ------------------------------------------------------------------
    # Rule write endpoints
    # ------------------------------------------------------------------
    @app.post("/admin/rules")
    async def _create_rule(
        request: Request,
        rule: dict = Body(...),
        expected_sha256: str | None = None,
        force: bool = False,
        actor: str = Depends(_require_auth),
    ) -> JSONResponse:
        data, path = _load_rules()
        _conflict_guard(path, expected_sha256, force)
        if not isinstance(rule, dict):
            raise AdminError("Rule must be an object", code="invalid_body")
        data["rules"].append(rule)
        return await _commit_rules(
            data, path, event="rule.create", actor=actor, request=request
        )

    @app.put("/admin/rules")
    async def _replace_rules(
        request: Request,
        body: dict = Body(...),
        expected_sha256: str | None = None,
        force: bool = False,
        actor: str = Depends(_require_auth),
    ) -> JSONResponse:
        data, path = _load_rules()
        _conflict_guard(path, expected_sha256, force)
        rules = body.get("rules")
        if not isinstance(rules, list):
            raise AdminError("Body must contain a 'rules' array", code="invalid_body")
        data["rules"] = rules
        return await _commit_rules(
            data, path, event="rule.replace", actor=actor, request=request
        )

    @app.patch("/admin/rules/{rule_id}")
    async def _update_rule(
        request: Request,
        rule_id: str,
        patch: dict = Body(...),
        expected_sha256: str | None = None,
        force: bool = False,
        actor: str = Depends(_require_auth),
    ) -> JSONResponse:
        data, path = _load_rules()
        _conflict_guard(path, expected_sha256, force)
        target = None
        for rule in data["rules"]:
            if isinstance(rule, dict) and str(rule.get("id", "")) == rule_id:
                target = rule
                break
        if target is None:
            raise AdminError(
                f"Unknown rule: {rule_id}", status=404, code="rule_not_found"
            )
        before = dict(target)
        target.update(patch)
        target["id"] = rule_id
        return await _commit_rules(
            data,
            path,
            event="rule.update",
            actor=actor,
            request=request,
            target=rule_id,
            before=before,
        )

    @app.delete("/admin/rules/{rule_id}")
    async def _delete_rule(
        request: Request,
        rule_id: str,
        expected_sha256: str | None = None,
        force: bool = False,
        actor: str = Depends(_require_auth),
    ) -> JSONResponse:
        data, path = _load_rules()
        _conflict_guard(path, expected_sha256, force)
        remaining = [
            rule
            for rule in data["rules"]
            if not (isinstance(rule, dict) and str(rule.get("id", "")) == rule_id)
        ]
        if len(remaining) == len(data["rules"]):
            raise AdminError(
                f"Unknown rule: {rule_id}", status=404, code="rule_not_found"
            )
        data["rules"] = remaining
        return await _commit_rules(
            data,
            path,
            event="rule.delete",
            actor=actor,
            request=request,
            target=rule_id,
        )

    # ------------------------------------------------------------------
    # Config write endpoint
    # ------------------------------------------------------------------
    @app.patch("/admin/config")
    async def _patch_config(
        request: Request,
        patch: dict = Body(...),
        expected_sha256: str | None = None,
        force: bool = False,
        actor: str = Depends(_require_auth),
    ) -> JSONResponse:
        engine = _engine()
        keys = set(patch)
        rejected = keys - HOT_RELOAD_GLOBAL_KEYS
        if rejected:
            raise AdminError(
                "Keys are not hot-reloadable: " + ", ".join(sorted(rejected)),
                code="not_hot_reloadable",
                details={"allowed": sorted(HOT_RELOAD_GLOBAL_KEYS)},
            )
        async with engine.lock:
            raw = _load_config_roundtrip(engine)
            _conflict_guard(engine.config_path, expected_sha256, force)
            global_section = raw.setdefault("global", {})
            if not isinstance(global_section, dict):
                raise AdminError(
                    "global section is not an object", code="invalid_config"
                )
            before = {key: global_section.get(key) for key in patch}
            global_section.update(patch)
            engine.validate_global(raw)
            backup_path = config_io.backup_file(engine.config_path)
            _write_structured(raw, engine.config_path, backup=False)
            engine.apply_config(raw)
        audit.record(
            "config.update",
            actor=actor,
            source_ip=_client_ip(request),
            before=before,
            after=patch,
            result="ok",
        )
        return _ok(
            {
                "updated": sorted(keys),
                "backup": str(backup_path) if backup_path else None,
                "sha256": config_io.file_sha256(engine.config_path),
            }
        )

    # ------------------------------------------------------------------
    # Plugin endpoints
    # ------------------------------------------------------------------
    @app.post("/admin/plugins/{name}/{action}")
    async def _plugin_action(
        request: Request,
        name: str,
        action: str,
        force: bool = False,
        actor: str = Depends(_require_auth),
    ) -> JSONResponse:
        if plugin_manager is None:
            raise AdminError(
                "Plugin manager not available",
                status=503,
                code="plugin_manager_unavailable",
            )
        engine = _engine()
        try:
            async with engine.lock:
                if action == "enable":
                    await plugin_manager.enable_plugin(name)
                elif action == "disable":
                    await plugin_manager.disable_plugin(name, force=force)
                elif action == "restart":
                    await plugin_manager.restart_plugin(name)
                else:
                    raise AdminError(
                        f"Unknown action: {action}",
                        status=404,
                        code="unknown_action",
                    )
        except Exception as exc:
            status = 409 if type(exc).__name__ == "PluginDependencyError" else 400
            audit.record(
                f"plugin.{action}",
                actor=actor,
                source_ip=_client_ip(request),
                target=name,
                result="fail",
                error=str(exc),
            )
            raise AdminError(str(exc), status=status, code="plugin_error") from exc
        audit.record(
            f"plugin.{action}",
            actor=actor,
            source_ip=_client_ip(request),
            target=name,
            result="ok",
        )
        return _ok({"name": name, "action": action})

    # ------------------------------------------------------------------
    # Driver endpoints
    # ------------------------------------------------------------------
    @app.post("/admin/drivers/{instance_id}/restart")
    async def _restart_driver(
        request: Request,
        instance_id: str,
        actor: str = Depends(_require_auth),
    ) -> JSONResponse:
        if driver_manager is None:
            raise AdminError(
                "Driver manager not available",
                status=503,
                code="driver_manager_unavailable",
            )
        if instance_id not in driver_manager.drivers:
            raise AdminError(
                f"Unknown driver: {instance_id}",
                status=404,
                code="driver_not_found",
            )
        engine = _engine()
        async with engine.lock:
            await driver_manager.restart_driver(instance_id)
        audit.record(
            "driver.restart",
            actor=actor,
            source_ip=_client_ip(request),
            target=instance_id,
            result="ok",
        )
        return _ok({"instance_id": instance_id, "action": "restart"})

    @app.post("/admin/drivers/{instance_id}/reload")
    async def _reload_driver(
        request: Request,
        instance_id: str,
        actor: str = Depends(_require_auth),
    ) -> JSONResponse:
        if driver_manager is None:
            raise AdminError(
                "Driver manager not available",
                status=503,
                code="driver_manager_unavailable",
            )
        if instance_id not in driver_manager.drivers:
            raise AdminError(
                f"Unknown driver: {instance_id}",
                status=404,
                code="driver_not_found",
            )
        engine = _engine()
        raw = engine.read_config_file()
        from drivers.registry import all_drivers

        inst_raw = None
        config_cls = None
        for platform, (cls, _driver) in all_drivers().items():
            candidate = (raw.get(platform, {}) or {}).get(instance_id)
            if candidate is not None:
                inst_raw, config_cls = candidate, cls
                break
        if inst_raw is None or config_cls is None:
            raise AdminError(
                f"No configuration for driver: {instance_id}",
                status=404,
                code="driver_config_not_found",
            )
        try:
            cfg = config_cls.model_validate(inst_raw)
        except Exception as exc:
            raise AdminError(
                f"Invalid driver configuration: {exc}",
                code="invalid_driver_config",
            ) from exc
        async with engine.lock:
            await driver_manager.reload_driver(instance_id, cfg)
            engine.note_driver_config(instance_id, inst_raw)
        audit.record(
            "driver.reload",
            actor=actor,
            source_ip=_client_ip(request),
            target=instance_id,
            result="ok",
        )
        return _ok({"instance_id": instance_id, "action": "reload"})

    # ------------------------------------------------------------------
    # Full reload + deprecated alias
    # ------------------------------------------------------------------
    @app.post("/admin/reload")
    async def _reload_all(
        request: Request,
        actor: str = Depends(_require_auth),
    ) -> JSONResponse:
        result = await _engine().reload_all()
        audit.record(
            "reload.full",
            actor=actor,
            source_ip=_client_ip(request),
            result="ok",
            after=result,
        )
        return _ok(result)

    @app.post("/admin/reload/{instance_id}")
    async def _reload_instance_deprecated(
        request: Request,
        instance_id: str,
        actor: str = Depends(_require_auth),
    ) -> JSONResponse:
        if driver_manager is None:
            raise AdminError(
                "Driver manager not available",
                status=503,
                code="driver_manager_unavailable",
            )
        if instance_id not in driver_manager.drivers:
            raise AdminError(
                f"Unknown driver: {instance_id}",
                status=404,
                code="driver_not_found",
            )
        engine = _engine()
        async with engine.lock:
            await driver_manager.restart_driver(instance_id)
        audit.record(
            "driver.restart",
            actor=actor,
            source_ip=_client_ip(request),
            target=instance_id,
            result="ok",
        )
        return _ok(
            {
                "instance_id": instance_id,
                "action": "restart",
                "deprecated": True,
                "use": f"/_nextbridge/admin/drivers/{instance_id}/restart",
            }
        )

    logger.info("Admin API routes registered (/_nextbridge/*)")
    return app
