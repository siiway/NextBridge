from __future__ import annotations

import asyncio


from drivers.qq import QqDriver
from services.bridge import Bridge
from services.config_schema import GlobalConfig
from services.message import NormalizedMessage
from services.util import strip_invisible_chars


class TestStripInvisibleChars:
    def test_removes_zero_width_and_control_chars(self):
        # U+200B zero width space, U+200E LRM, U+0000 NUL, U+202E RLO
        assert strip_invisible_chars("&a\u200bb\u200ec\u0000d\u202ee") == "&abcde"

    def test_keeps_visible_and_normal_space(self):
        assert strip_invisible_chars("王 小明") == "王 小明"
        assert strip_invisible_chars("&ÿRñ|killjsj~喵") == "&ÿRñ|killjsj~喵"

    def test_returns_original_object_when_clean(self):
        value = "plain"
        assert strip_invisible_chars(value) is value

    def test_zwj_and_variation_selector_removed(self):
        # ZWJ + VS16 are format characters; they are dropped by design.
        assert strip_invisible_chars("a\u200db\ufe0f") == "ab"

    def test_removes_line_and_paragraph_separators(self):
        assert strip_invisible_chars("a\u2028b\u2029c") == "abc"

    def test_handles_empty_and_non_string(self):
        assert strip_invisible_chars("") == ""
        assert strip_invisible_chars(None) == ""
        assert strip_invisible_chars(123) == ""


class TestBridgeNameSanitize:
    def test_default_is_enabled(self):
        assert GlobalConfig().sanitize_nickname is True
        assert Bridge().sanitize_nickname is True

    def test_sanitize_names_strips_nickname_and_username(self):
        bridge = Bridge()
        msg = NormalizedMessage(nickname="A\u200bB", username="C\u200eD")
        bridge.sanitize_names(msg)
        assert msg.nickname == "AB"
        assert msg.username == "CD"

    def test_sanitize_names_respects_disabled_flag(self):
        bridge = Bridge()
        bridge.sanitize_nickname = False
        msg = NormalizedMessage(nickname="A\u200bB", username="C\u200eD")
        bridge.sanitize_names(msg)
        assert msg.nickname == "A\u200bB"
        assert msg.username == "C\u200eD"

    def test_on_message_sanitizes_before_formatting(self):
        bridge = Bridge()
        captured: list[str] = []

        async def sender(channel, text, **kwargs):
            captured.append(text)
            return None

        bridge.register_sender("target", sender)
        bridge.apply_rules(
            [
                {
                    "id": "r1",
                    "from": {"src": {"id": "ch1"}},
                    "to": {"target": {"id": "ch2"}},
                    "msg": {"msg_format": "{nickname}|{msg}"},
                }
            ]
        )
        msg = NormalizedMessage(
            platform="test",
            instance_id="src",
            channel={"id": "ch1"},
            nickname="ali\u200bce",
            user_id="u1",
            text="hi",
            message_id="m1",
        )
        asyncio.run(bridge.on_message(msg))
        assert captured == ["alice|hi"]

    def test_build_formatted_sanitizes_when_msg_was_not_sanitized(self):
        bridge = Bridge()
        msg = NormalizedMessage(nickname="bo\u200bb", username="bo\u200bb")
        text, extra = bridge._build_formatted(msg, {"msg_format": "{user}/{nickname}"})
        assert text == "bob/bob"
        assert extra["username"] == "@bob"
        assert extra["nickname"] == "bob"
        assert extra["user"] == "bob"


class TestQqForwardNames:
    def test_forward_node_sender_fields_strips_invisible(self):
        node = {"sender": {"user_id": 10001, "nickname": "ki\u200bll"}}
        user_id, nickname = QqDriver._forward_node_sender_fields(node)
        assert user_id == "10001"
        assert nickname == "kill"
