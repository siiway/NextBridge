from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from services import config_io
from services.admin_api import build_admin_app
from services.bridge import Bridge
from services.metrics import MetricsCollector
from services.reload import ReloadEngine


class FakeDriverManager:
    def __init__(self):
        self.drivers: dict[str, object] = {}
        self.restarted: list[str] = []

    def get_status(self) -> dict:
        return {}

    async def restart_driver(self, instance_id):
        self.restarted.append(instance_id)


class FakePluginManager:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def get_status(self) -> dict:
        return {}

    async def enable_plugin(self, name):
        self.calls.append(("enable", name))

    async def disable_plugin(self, name, *, force=False):
        self.calls.append(("disable", name))

    async def restart_plugin(self, name):
        self.calls.append(("restart", name))


def _write_rules(path: Path, rules: list[dict]) -> None:
    path.write_text(json.dumps({"rules": rules}), encoding="utf-8")


def _write_config(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    rules_path = tmp_path / "rules.yaml"
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        {"global": {"command_prefix": "nb", "database": {"url": "sqlite://"}}},
    )
    _write_rules(rules_path, [{"id": "r1", "type": "forward"}])
    monkeypatch.setattr("services.reload.config_io.find_rules", lambda _d: rules_path)
    bridge = Bridge()
    engine = ReloadEngine(bridge, config_path=config_path)
    metrics = MetricsCollector()
    dm: Any = FakeDriverManager()
    pm: Any = FakePluginManager()
    app = build_admin_app(
        version="test",
        bridge=bridge,
        driver_manager=dm,
        plugin_manager=pm,
        reload_engine=engine,
        metrics=metrics,
        admin_enabled=True,
        admin_user="u",
        admin_password="p",
    )
    return {
        "app": app,
        "bridge": bridge,
        "engine": engine,
        "metrics": metrics,
        "dm": dm,
        "pm": pm,
        "rules_path": rules_path,
        "config_path": config_path,
    }


def _client(app, *, user="u", password="p"):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        auth=(user, password),
    )


@pytest.mark.asyncio
async def test_health_is_public(env):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env["app"]), base_url="http://test"
    ) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_admin_disabled_hides_routes():
    app = build_admin_app(version="test", admin_enabled=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/drivers")).status_code == 404
        assert (await client.get("/metrics")).status_code == 404


@pytest.mark.asyncio
async def test_auth_required_and_wrong_credentials(env):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env["app"]), base_url="http://test"
    ) as client:
        assert (await client.get("/drivers")).status_code == 401
    async with _client(env["app"], password="wrong") as client:
        assert (await client.get("/drivers")).status_code == 401
    async with _client(env["app"], user="wrong") as client:
        assert (await client.get("/drivers")).status_code == 401
    async with _client(env["app"]) as client:
        assert (await client.get("/drivers")).status_code == 200


@pytest.mark.asyncio
async def test_rules_crud(env):
    bridge = env["bridge"]
    rules_path = env["rules_path"]
    async with _client(env["app"]) as client:
        listing = (await client.get("/rules")).json()
        assert listing["ok"] is True
        assert len(listing["data"]["rules"]) == 1
        sha = listing["data"]["sha256"]

        created = await client.post(
            "/admin/rules",
            json={"id": "r2", "type": "forward", "from": {}, "to": {}},
            params={"expected_sha256": sha},
        )
        assert created.status_code == 200, created.text
        assert created.json()["data"]["rules"] == 2
        assert len(bridge._rules) == 2

        sha = created.json()["data"]["sha256"]
        patched = await client.patch(
            "/admin/rules/r2",
            json={"msg": {"msg_format": "x"}},
            params={"expected_sha256": sha},
        )
        assert patched.status_code == 200, patched.text

        sha = patched.json()["data"]["sha256"]
        deleted = await client.delete(
            "/admin/rules/r1", params={"expected_sha256": sha}
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["data"]["rules"] == 1

    assert rules_path.with_suffix(".yaml.bak").exists()
    saved = config_io.load_config(rules_path)
    assert [r["id"] for r in saved["rules"]] == ["r2"]


@pytest.mark.asyncio
async def test_rules_conflict_detection(env):
    rules_path = env["rules_path"]
    async with _client(env["app"]) as client:
        sha = (await client.get("/rules")).json()["data"]["sha256"]
    _write_rules(rules_path, [{"id": "r1", "type": "forward"}, {"id": "r9"}])
    async with _client(env["app"]) as client:
        conflict = await client.post(
            "/admin/rules",
            json={"type": "forward"},
            params={"expected_sha256": sha},
        )
        assert conflict.status_code == 409
        forced = await client.post(
            "/admin/rules",
            json={"type": "forward"},
            params={"expected_sha256": sha, "force": "true"},
        )
        assert forced.status_code == 200


@pytest.mark.asyncio
async def test_config_patch_whitelist(env):
    bridge = env["bridge"]
    config_path = env["config_path"]
    async with _client(env["app"]) as client:
        ok = await client.patch("/admin/config", json={"command_prefix": "zz"})
        assert ok.status_code == 200, ok.text
        assert bridge.command_prefix == "zz"

        rejected = await client.patch(
            "/admin/config", json={"database": {"url": "sqlite://"}}
        )
        assert rejected.status_code == 400
        assert rejected.json()["error"]["code"] == "not_hot_reloadable"
    saved = config_io.load_config(config_path)
    assert saved["global"]["command_prefix"] == "zz"


@pytest.mark.asyncio
async def test_config_read_redacts_secrets(env):
    async with _client(env["app"]) as client:
        data = (await client.get("/config")).json()["data"]["config"]
    assert data["global"]["database"]["url"] == "sqlite://"


@pytest.mark.asyncio
async def test_driver_and_plugin_routes(env):
    async with _client(env["app"]) as client:
        assert (await client.get("/drivers")).json()["data"]["drivers"] == {}
        assert (await client.post("/admin/drivers/nope/restart")).status_code == 404
        resp = await client.post("/admin/plugins/foo/enable")
        assert resp.status_code == 200
    assert env["pm"].calls == [("enable", "foo")]


@pytest.mark.asyncio
async def test_metrics_endpoint(env):
    env["metrics"].inc_message("telegram", "i1", "recv")
    async with _client(env["app"]) as client:
        resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert b"nextbridge_messages_total" in resp.content


@pytest.mark.asyncio
async def test_rules_edit_preserves_yaml_comments(env):
    rules_path = env["rules_path"]
    rules_path.write_text(
        "# keep me\nrules:\n  - id: r1\n    type: forward\n",
        encoding="utf-8",
    )
    async with _client(env["app"]) as client:
        sha = (await client.get("/rules")).json()["data"]["sha256"]
        resp = await client.patch(
            "/admin/rules/r1",
            json={"msg": {"msg_format": "x"}},
            params={"expected_sha256": sha},
        )
        assert resp.status_code == 200, resp.text
    assert "# keep me" in rules_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_create_rule_malformed_document(env):
    env["rules_path"].write_text("rules: not-a-list\n", encoding="utf-8")
    async with _client(env["app"]) as client:
        resp = await client.post("/admin/rules", json={"type": "forward"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_rules_file"
