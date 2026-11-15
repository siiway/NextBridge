from unittest.mock import MagicMock, patch

import pytest
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from drivers.feishu import FeishuConfig, FeishuDriver


@pytest.mark.parametrize(
    ("chat_type", "expected_is_dm"),
    [("p2p", True), ("group", False)],
)
def test_message_event_reads_chat_type_from_message(chat_type, expected_is_dm):
    bridge = MagicMock()
    bridge.on_message.return_value = object()
    driver = FeishuDriver(
        "fs_main",
        FeishuConfig(app_id="cli_test", app_secret="secret"),
        bridge,
    )
    driver._loop = MagicMock()
    driver._fetch_user_info = MagicMock(return_value=("Alice", ""))

    data = P2ImMessageReceiveV1(
        {
            "event": {
                "sender": {"sender_id": {"open_id": "ou_test"}},
                "message": {
                    "message_id": "om_test",
                    "chat_id": "oc_test",
                    "chat_type": chat_type,
                    "message_type": "text",
                    "content": '{"text":"hello"}',
                },
            }
        }
    )

    with patch("drivers.feishu.asyncio.run_coroutine_threadsafe") as submit:
        driver._on_message_event(data)

    normalized = bridge.on_message.call_args.args[0]
    assert normalized.text == "hello"
    assert normalized.is_dm is expected_is_dm
    submit.assert_called_once_with(bridge.on_message.return_value, driver._loop)
