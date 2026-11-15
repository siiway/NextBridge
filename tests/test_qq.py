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
