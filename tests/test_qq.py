import asyncio
from unittest.mock import MagicMock

from drivers.qq import QqConfig, QqDriver


def test_reverse_mode_mounts_instance_specific_websocket_path():
    http_server = MagicMock()
    driver = QqDriver(
        "qq_main",
        QqConfig(connection_mode="reverse"),
        MagicMock(),
    )
    driver.attach_http_server(http_server)

    driver._ensure_reverse_ws_mount()

    http_server.mount.assert_called_once()
    mount_args = http_server.mount.call_args.kwargs
    assert mount_args["instance_id"] == "qq_main/reverse-ws"
    assert mount_args["path"] == "/onebot/v11/qq_main"
    assert driver._reverse_mount_registered


def test_reverse_mode_uses_configured_websocket_path():
    driver = QqDriver(
        "qq_main",
        QqConfig(connection_mode="reverse", reverse_ws_path="custom/napcat"),
        MagicMock(),
    )

    assert driver._reverse_ws_path() == "/custom/napcat"


# ---------------------------------------------------------------------------
# Face GIF loading: local database first, remote host only as a fallback
# ---------------------------------------------------------------------------


def _driver(**kwargs) -> QqDriver:
    return QqDriver("qq_main", QqConfig(**kwargs), MagicMock())


def test_face_gif_prefers_local_database(monkeypatch):
    monkeypatch.setattr("drivers.qq._load_face_gif", lambda face_id: b"local-gif")

    async def fail_fetch(*args, **kwargs):
        raise AssertionError("remote host must not be contacted when local hit")

    monkeypatch.setattr("drivers.qq.media.fetch", fail_fetch)

    assert asyncio.run(_driver()._fetch_face_gif(14)) == b"local-gif"


def test_face_gif_falls_back_to_remote_host(monkeypatch):
    monkeypatch.setattr("drivers.qq._load_face_gif", lambda face_id: None)
    calls = []

    async def fake_fetch(url, max_bytes, proxy=None):
        calls.append(url)
        return b"remote-gif", "image/gif"

    monkeypatch.setattr("drivers.qq.media.fetch", fake_fetch)

    import asyncio

    driver = _driver(cqface_gif_host="https://cqface.example.com/dist")
    assert asyncio.run(driver._fetch_face_gif(14)) == b"remote-gif"
    assert calls == ["https://cqface.example.com/dist/14.gif"]


def test_face_gif_fallback_disabled_when_host_is_false(monkeypatch):
    monkeypatch.setattr("drivers.qq._load_face_gif", lambda face_id: None)

    async def fail_fetch(*args, **kwargs):
        raise AssertionError("remote host disabled, must not fetch")

    monkeypatch.setattr("drivers.qq.media.fetch", fail_fetch)

    assert asyncio.run(_driver(cqface_gif_host=False)._fetch_face_gif(14)) is None


def test_face_gif_missing_everywhere_returns_none(monkeypatch):
    monkeypatch.setattr("drivers.qq._load_face_gif", lambda face_id: None)

    async def fake_fetch(url, max_bytes, proxy=None):
        return None

    monkeypatch.setattr("drivers.qq.media.fetch", fake_fetch)

    assert asyncio.run(_driver()._fetch_face_gif(9999)) is None


def test_legacy_forward_render_cqface_gif_alias_still_works():
    """The pre-rename key must keep working so existing configs do not break."""
    driver = _driver(forward_render_cqface_gif="https://legacy.example.com/gif")
    assert driver._cqface_message_gif_host() == "https://legacy.example.com/gif/"


def test_face_gif_reads_from_synced_data_directory(tmp_path, monkeypatch):
    """A synced copy under the data dir wins over the in-repo copy."""
    (tmp_path / "cqface-gif").mkdir()
    (tmp_path / "cqface-gif" / "14.gif").write_bytes(b"synced-gif")
    monkeypatch.setenv("NEXTBRIDGE_DATA_PATH", str(tmp_path))

    from drivers.qq import _load_face_gif

    assert _load_face_gif(14) == b"synced-gif"


def test_face_gif_missing_from_every_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXTBRIDGE_DATA_PATH", str(tmp_path))
    monkeypatch.setattr("drivers.qq._face_db_dirs", lambda: (tmp_path,))

    from drivers.qq import _load_face_gif

    assert _load_face_gif(14) is None


def test_cached_qid_prefers_memory_cache(monkeypatch):
    driver = _driver()
    driver._qid_cache["10001"] = "custom_qid"

    def fail(*args, **kwargs):
        raise AssertionError("database must not be hit on a memory cache hit")

    monkeypatch.setattr("drivers.qq.msg_db", fail)

    assert driver._cached_qid("10001") == "custom_qid"


def test_cached_qid_uses_persisted_row(monkeypatch):
    driver = _driver()
    fake_db = MagicMock()
    fake_db.get_user_qid.return_value = "persisted_qid"
    monkeypatch.setattr("drivers.qq.msg_db", lambda: fake_db)

    assert driver._cached_qid("10002") == "persisted_qid"
    fake_db.get_user_qid.assert_called_once_with(driver.instance_id, "10002")
    assert driver._qid_cache["10002"] == "persisted_qid"


def test_cached_qid_never_calls_the_api(monkeypatch):
    driver = _driver()
    fake_db = MagicMock()
    fake_db.get_user_qid.return_value = None
    monkeypatch.setattr("drivers.qq.msg_db", lambda: fake_db)

    def fail(*args, **kwargs):
        raise AssertionError("get_stranger_info must stay off the message path")

    monkeypatch.setattr(driver, "_get_qid", fail)

    assert driver._cached_qid("10003") == ""
