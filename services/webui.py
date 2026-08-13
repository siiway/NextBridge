"""WebUI management plane.

Serves the NextBridge WebUI on the shared HTTP server:

  - REST API under ``/api`` for config/rules editing with token auth
  - static SPA from the repository ``dist/`` directory (built from nb-webui)

Credentials live in ``data/webui.json`` — kept separate from ``config.json``
so config saves can never clobber the password hash.  The default account is
``admin / admin`` and the password must be changed before the panel can be
used.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import hmac
import inspect
import json
import secrets
import textwrap
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

import services.config as config
import services.config_io as config_io
import services.logger as log
from drivers.registry import get_meta
from services.config_schema import GlobalConfig, RulesFile

logger = log.get_logger("webui")

_TOKEN_TTL_SECONDS = 24 * 60 * 60
_MIN_PASSWORD_LEN = 8

_DIST_MISSING_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>NextBridge WebUI 未安装</title>
<style>
  body { background: #0a0a0a; color: #e5e5e5; font-family: system-ui, sans-serif;
         display: flex; min-height: 100vh; margin: 0; align-items: center; justify-content: center; }
  main { max-width: 640px; padding: 2rem; }
  h1 { font-size: 1.5rem; }
  pre { background: #171717; border: 1px solid #262626; border-radius: 8px;
        padding: 1rem; overflow-x: auto; line-height: 1.6; }
  a { color: #60a5fa; }
</style>
</head>
<body>
<main>
  <h1>NextBridge WebUI</h1>
  <p>API 服务已就绪,但前端页面尚未构建。请按以下步骤导入前端:</p>
  <pre>git clone https://github.com/LeiSureLyYrsc/nb-webui.git
cd nb-webui
bun install
bun run build
# 将 nb-webui/dist 目录中的所有文件复制到 NextBridge 的 dist/ 目录后重启</pre>
  <p>详细教程见 <a href="https://nextbridge.siiway.org">NextBridge 文档站</a>。</p>
</main>
</body>
</html>
"""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64url(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


class WebuiAuth:
    """Persistent credential store + stateless HMAC session tokens."""

    def __init__(self, path: Path):
        self.path = path
        self._data = self._load_or_create()

    @staticmethod
    def _hash_password(password: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)

    def _load_or_create(self) -> dict[str, Any]:
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                for key in (
                    "username",
                    "password_salt",
                    "password_hash",
                    "session_secret",
                ):
                    if not isinstance(data.get(key), str) or not data[key]:
                        raise ValueError(f"missing key: {key}")
                data.setdefault("must_change_password", True)
                return data
            except Exception:
                logger.opt(exception=True).warning(
                    f"WebUI credentials file {self.path} unreadable — recreating"
                )
        salt = secrets.token_bytes(16)
        data = {
            "username": "admin",
            "password_salt": _b64url(salt),
            "password_hash": _b64url(self._hash_password("admin", salt)),
            "must_change_password": True,
            "session_secret": secrets.token_hex(32),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._save(data)
        logger.warning(
            f"WebUI credentials created at {self.path} — default account is "
            "admin / admin, the password must be changed on first login"
        )
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    @property
    def username(self) -> str:
        return str(self._data.get("username", "admin"))

    @property
    def must_change_password(self) -> bool:
        return bool(self._data.get("must_change_password", True))

    def verify_password(self, password: str) -> bool:
        try:
            salt = _unb64url(str(self._data["password_salt"]))
            expected = _unb64url(str(self._data["password_hash"]))
        except Exception:
            return False
        return hmac.compare_digest(self._hash_password(password, salt), expected)

    def change_password(self, old: str, new: str) -> tuple[bool, str]:
        """Update the password.  Returns ``(ok, error_message)``."""
        if not self.verify_password(old):
            return False, "原密码不正确"
        if len(new) < _MIN_PASSWORD_LEN:
            return False, f"新密码长度不能少于 {_MIN_PASSWORD_LEN} 位"
        if new == old:
            return False, "新密码不能与原密码相同"
        salt = secrets.token_bytes(16)
        self._data["password_salt"] = _b64url(salt)
        self._data["password_hash"] = _b64url(self._hash_password(new, salt))
        self._data["must_change_password"] = False
        # Rotate the session secret so any bearer tokens issued before this
        # password change are invalidated immediately.
        self._data["session_secret"] = secrets.token_hex(32)
        self._save(self._data)
        return True, ""

    def create_token(self) -> str:
        secret = self._data["session_secret"].encode()
        payload = f"{self.username}:{int(time.time()) + _TOKEN_TTL_SECONDS}"
        payload_b64 = _b64url(payload.encode())
        sig = hmac.new(secret, payload_b64.encode(), hashlib.sha256).digest()
        return f"{payload_b64}.{_b64url(sig)}"

    def verify_token(self, token: str) -> str | None:
        """Return the username if *token* is valid and not expired."""
        try:
            payload_b64, sig_b64 = token.split(".", 1)
            secret = self._data["session_secret"].encode()
            expected = hmac.new(secret, payload_b64.encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(_unb64url(sig_b64), expected):
                return None
            payload = _unb64url(payload_b64).decode()
            username, expiry = payload.rsplit(":", 1)
            if int(expiry) < int(time.time()):
                return None
            return username if username == self.username else None
        except Exception:
            return None


class _LoginRateLimiter:
    """In-memory per-IP login attempt limiter."""

    def __init__(self, max_attempts: int = 10, window_seconds: int = 60):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = {}
        self._last_prune: float = time.time()

    def _prune_stale_ips(self, now: float) -> None:
        """Periodically drop IPs whose last attempt is older than the window.

        Bounds the size of ``_attempts`` for long-lived processes so the
        per-IP state does not grow without limit.
        """
        if now - self._last_prune < self.window_seconds:
            return
        cutoff = now - self.window_seconds
        stale = [ip for ip, q in self._attempts.items() if not q or q[-1] < cutoff]
        for ip in stale:
            self._attempts.pop(ip, None)
        self._last_prune = now

    def allowed(self, ip: str) -> bool:
        now = time.time()
        self._prune_stale_ips(now)
        queue = self._attempts.setdefault(ip, deque())
        while queue and now - queue[0] > self.window_seconds:
            queue.popleft()
        if len(queue) >= self.max_attempts:
            return False
        queue.append(now)
        return True


class _LoginBody(BaseModel):
    username: str
    password: str


class _ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str


def _validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {
            "path": ".".join(str(p) for p in e.get("loc", [])),
            "message": str(e.get("msg", "")),
            "type": str(e.get("type", "")),
        }
        for e in exc.errors(include_url=False)
    ]


def _field_docstrings(cls: type) -> dict[str, str]:
    """Extract attribute docstrings (``field: ... = ...`` followed by one)."""
    try:
        source = textwrap.dedent(inspect.getsource(cls))
        tree = ast.parse(source)
        node = next(
            n
            for n in tree.body
            if isinstance(n, ast.ClassDef) and n.name == cls.__name__
        )
    except (OSError, TypeError, StopIteration, SyntaxError):
        return {}
    result: dict[str, str] = {}
    for i, stmt in enumerate(node.body):
        target: str | None = None
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            target = stmt.target.id
        elif isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    target = t.id
                    break
        if target is None or i + 1 >= len(node.body):
            continue
        nxt = node.body[i + 1]
        if (
            isinstance(nxt, ast.Expr)
            and isinstance(nxt.value, ast.Constant)
            and isinstance(nxt.value.value, str)
        ):
            doc = inspect.cleandoc(nxt.value.value)
            if doc:
                result[target] = doc
    return result


def _collect_field_docstrings(cls: type[BaseModel]) -> dict[str, str]:
    """Collect field docstrings from *cls* and its non-pydantic bases."""
    merged: dict[str, str] = {}
    for klass in reversed(cls.__mro__):
        if klass is object or klass.__module__.startswith("pydantic"):
            continue
        merged.update(_field_docstrings(klass))
    return merged


def _apply_descriptions(schema: dict[str, Any], docstrings: dict[str, str]) -> None:
    props = schema.get("properties")
    if not isinstance(props, dict):
        return
    for name, desc in docstrings.items():
        if name in props and isinstance(props[name], dict):
            props[name].setdefault("description", desc)


def build_webui_app(
    *,
    config_path: Path,
    rules_path: Path,
    webui_json_path: Path,
    dist_dir: Path | None,
    registry: dict[str, tuple[type[BaseModel], type]],
    version: str,
) -> FastAPI:
    """Build the WebUI FastAPI sub-app (API + static frontend)."""
    auth = WebuiAuth(webui_json_path)
    limiter = _LoginRateLimiter()

    app = FastAPI(title="NextBridge WebUI", version=version)

    def _require_auth(request: Request) -> str:
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        if not token:
            token = request.query_params.get("token", "").strip()
        username = auth.verify_token(token)
        if username is None:
            raise HTTPException(status_code=401, detail="未登录或登录已过期")
        if auth.must_change_password:
            path = request.url.path
            if not path.endswith(("/api/auth/change-password", "/api/auth/status")):
                raise HTTPException(
                    status_code=403, detail="首次登录必须先修改默认密码"
                )
        return username

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    @app.post("/api/auth/login")
    async def login(body: _LoginBody, request: Request) -> dict[str, Any]:
        ip = request.client.host if request.client else "unknown"
        if not limiter.allowed(ip):
            raise HTTPException(status_code=429, detail="尝试次数过多,请稍后再试")
        if body.username == auth.username and auth.verify_password(body.password):
            logger.info(f"WebUI login success for '{body.username}' from {ip}")
            return {
                "token": auth.create_token(),
                "username": auth.username,
                "must_change_password": auth.must_change_password,
            }
        logger.warning(f"WebUI login failed for '{body.username}' from {ip}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    @app.post("/api/auth/change-password")
    async def change_password(
        body: _ChangePasswordBody,
        request: Request,
        username: str = Depends(_require_auth),
    ) -> dict[str, Any]:
        ok, msg = auth.change_password(body.old_password, body.new_password)
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        logger.info(f"WebUI password changed for '{username}'")
        return {"token": auth.create_token(), "must_change_password": False}

    @app.get("/api/auth/status", dependencies=[Depends(_require_auth)])
    async def auth_status() -> dict[str, Any]:
        return {
            "username": auth.username,
            "must_change_password": auth.must_change_password,
        }

    # ------------------------------------------------------------------
    # Info & schemas
    # ------------------------------------------------------------------

    @app.get("/api/info", dependencies=[Depends(_require_auth)])
    async def info() -> dict[str, Any]:
        platforms: dict[str, int] = {}
        try:
            raw = config_io.load_config(config_path)
            for key, value in raw.items():
                if key != "global" and isinstance(value, dict):
                    platforms[key] = len(value)
        except Exception:
            logger.opt(exception=True).warning("WebUI failed to read config file")
        return {
            "version": version,
            "config_path": str(config_path),
            "rules_path": str(rules_path),
            "platforms": platforms,
        }

    @app.get("/api/schemas", dependencies=[Depends(_require_auth)])
    async def schemas() -> dict[str, Any]:
        drivers: dict[str, Any] = {}
        meta: dict[str, Any] = {}
        for name, (config_cls, _driver_cls) in registry.items():
            schema = config_cls.model_json_schema()
            _apply_descriptions(schema, _collect_field_docstrings(config_cls))
            drivers[name] = schema
            dm = get_meta(name)
            meta[name] = {
                "description": (config_cls.__doc__ or "").strip(),
                "display_name": dm.get("display_name", name),
                "icon": dm.get("icon", ""),
                "channel_fields": dm.get("channel_fields", []),
            }
        global_schema = GlobalConfig.model_json_schema()
        _apply_descriptions(global_schema, _collect_field_docstrings(GlobalConfig))
        return {"global": global_schema, "drivers": drivers, "meta": meta}

    @app.get("/api/instances", dependencies=[Depends(_require_auth)])
    async def instances() -> dict[str, Any]:
        """返回所有已配置的实例列表 (实例 ID → 平台类型)."""
        result: dict[str, str] = {}
        try:
            raw = config_io.load_config(config_path)
            for key, value in raw.items():
                if key != "global" and isinstance(value, dict):
                    for inst_id in value:
                        result[inst_id] = key
        except Exception:
            pass
        return {"instances": result}

    # ------------------------------------------------------------------
    # Config file
    # ------------------------------------------------------------------

    @app.get("/api/config", dependencies=[Depends(_require_auth)])
    async def get_config() -> Any:
        try:
            return config_io.load_config(config_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"读取配置失败: {exc}") from exc

    @app.put("/api/config")
    async def put_config(
        payload: dict[str, Any] = Body(...),
        username: str = Depends(_require_auth),
    ) -> Any:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="配置必须是对象")

        errors: dict[str, list[dict[str, Any]]] = {}
        try:
            GlobalConfig.model_validate(payload.get("global", {}))
        except ValidationError as exc:
            errors["global"] = _validation_errors(exc)

        for platform, instances in payload.items():
            if platform == "global":
                continue
            entry = registry.get(platform)
            if entry is None:
                errors[platform] = [
                    {
                        "path": "",
                        "message": f"未知平台: {platform}",
                        "type": "unknown_platform",
                    }
                ]
                continue
            config_cls, _ = entry
            if not isinstance(instances, dict):
                errors[platform] = [
                    {
                        "path": "",
                        "message": "平台配置必须是对象(实例 ID → 配置)",
                        "type": "type_error",
                    }
                ]
                continue
            for inst_id, inst_raw in instances.items():
                try:
                    config_cls.model_validate(inst_raw)
                except ValidationError as exc:
                    for err in _validation_errors(exc):
                        err["path"] = f"{platform}.{inst_id}.{err['path']}".rstrip(".")
                        errors.setdefault(platform, []).append(err)

        if errors:
            return JSONResponse(
                status_code=422, content={"detail": "配置校验失败", "errors": errors}
            )

        try:
            config_io.save_config(payload, config_path)
            config.invalidate_cache()
            logger.info(f"WebUI: config saved by '{username}' to {config_path}")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"保存配置失败: {exc}") from exc
        return {"ok": True, "saved_to": str(config_path)}

    # ------------------------------------------------------------------
    # Rules file
    # ------------------------------------------------------------------

    @app.get("/api/rules", dependencies=[Depends(_require_auth)])
    async def get_rules() -> Any:
        try:
            if rules_path.is_file():
                return config_io.load_config(rules_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"读取规则失败: {exc}") from exc
        return {"rules": []}

    @app.put("/api/rules")
    async def put_rules(
        payload: dict[str, Any] = Body(...),
        username: str = Depends(_require_auth),
    ) -> Any:
        raw_rules = payload.get("rules") if isinstance(payload, dict) else None
        if not isinstance(raw_rules, list):
            raise HTTPException(
                status_code=400, detail='规则必须是 {"rules": [...]} 结构'
            )
        for idx, rule in enumerate(raw_rules):
            if not isinstance(rule, dict) or not rule:
                raise HTTPException(
                    status_code=400, detail=f"第 {idx + 1} 条规则必须是非空对象"
                )
        try:
            RulesFile.model_validate({"rules": raw_rules})
        except ValidationError as exc:
            raise HTTPException(
                status_code=400,
                detail="规则结构校验失败: "
                + "; ".join(
                    str(e.get("msg", "")) for e in exc.errors(include_url=False)
                ),
            ) from exc
        normalized = config.normalize_rules_with_ids(raw_rules)
        try:
            config_io.save_config({"rules": normalized}, rules_path)
            logger.info(f"WebUI: rules saved by '{username}' to {rules_path}")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"保存规则失败: {exc}") from exc
        return {"ok": True, "count": len(normalized), "saved_to": str(rules_path)}

    # ------------------------------------------------------------------
    # Static frontend (must be mounted last so API routes win)
    # ------------------------------------------------------------------

    if dist_dir is not None and dist_dir.is_dir():
        app.mount(
            "/", StaticFiles(directory=str(dist_dir), html=True), name="webui-static"
        )
    else:

        @app.get("/", include_in_schema=False)
        async def index() -> HTMLResponse:
            return HTMLResponse(_DIST_MISSING_HTML)

    return app
