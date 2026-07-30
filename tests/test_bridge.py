from __future__ import annotations

import asyncio

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.bridge import Bridge, _collect_sensitive
from services.message import NormalizedMessage


@pytest.fixture
def bridge():
    return Bridge()


@pytest.fixture
def msg():
    return NormalizedMessage(
        platform="test",
        instance_id="src_inst",
        channel={"id": "ch1"},
        nickname="TestUser",
        user_id="user123",
        text="Hello world",
        message_id="msg001",
    )


class TestBuildBridgeId:
    def test_with_message_id(self, bridge):
        msg = NormalizedMessage(message_id="abc123", instance_id="inst1")
        result = bridge._build_bridge_id("rule1", msg)
        assert result == "rule1:inst1:abc123"

    def test_without_message_id_is_deterministic(self, bridge):
        msg = NormalizedMessage(
            instance_id="inst1",
            channel={"id": "ch1"},
            user_id="u1",
            text="hello",
            time="12:00",
        )
        result1 = bridge._build_bridge_id("rule1", msg)
        result2 = bridge._build_bridge_id("rule1", msg)
        assert result1 == result2
        assert result1.startswith("rule1:")
        assert ":" in result1


class TestShouldSkipEcho:
    def test_strict_mode_same_instance_same_channel(self, bridge):
        bridge.strict_echo_match = True
        assert bridge._should_skip_echo(
            "inst1",
            {"id": "ch1"},
            NormalizedMessage(instance_id="inst1", channel={"id": "ch1"}),
        )

    def test_strict_mode_same_instance_diff_channel(self, bridge):
        bridge.strict_echo_match = True
        assert not bridge._should_skip_echo(
            "inst1",
            {"id": "ch2"},
            NormalizedMessage(instance_id="inst1", channel={"id": "ch1"}),
        )

    def test_default_mode_same_instance(self, bridge):
        bridge.strict_echo_match = False
        assert bridge._should_skip_echo(
            "inst1",
            {"id": "ch2"},
            NormalizedMessage(instance_id="inst1", channel={"id": "ch1"}),
        )

    def test_default_mode_same_channel(self, bridge):
        bridge.strict_echo_match = False
        assert bridge._should_skip_echo(
            "inst2",
            {"id": "ch1"},
            NormalizedMessage(instance_id="inst1", channel={"id": "ch1"}),
        )

    def test_no_match(self, bridge):
        bridge.strict_echo_match = False
        assert not bridge._should_skip_echo(
            "inst3",
            {"id": "ch3"},
            NormalizedMessage(instance_id="inst1", channel={"id": "ch1"}),
        )


class TestCollectSensitive:
    def test_collects_token(self):
        found = set()
        _collect_sensitive({"bot": {"token": "abc123", "name": "mybot"}}, found)
        assert "abc123" in found

    def test_collects_webhook_url(self):
        found = set()
        _collect_sensitive({"webhook_url": "https://hook.example.com/abc"}, found)
        assert "https://hook.example.com/abc" in found

    def test_skips_non_sensitive_keys(self):
        found = set()
        _collect_sensitive({"name": "mybot", "enabled": True}, found)
        assert len(found) == 0

    def test_collects_secret(self):
        found = set()
        _collect_sensitive({"access_token": "super_secret_key"}, found)
        assert "super_secret_key" in found

    def test_skip_empty_string(self):
        found = set()
        _collect_sensitive({"token": ""}, found)
        assert len(found) == 0


class TestIsSensitive:
    def test_no_sensitive_values(self, bridge):
        bridge._sensitive = frozenset()
        assert not bridge._is_sensitive("hello world")

    def test_contains_sensitive(self, bridge):
        bridge._sensitive = frozenset(["secret123"])
        assert bridge._is_sensitive("my token is secret123")

    def test_not_contains_sensitive(self, bridge):
        bridge._sensitive = frozenset(["secret123"])
        assert not bridge._is_sensitive("hello world")


class TestParsePingCommand:
    def test_valid_ping(self, bridge):
        assert bridge._parse_ping_command("/ping RhenCloud") == "RhenCloud"

    def test_ping_with_at(self, bridge):
        assert bridge._parse_ping_command("/ping @RhenCloud") == "RhenCloud"

    def test_ping_no_args(self, bridge):
        assert bridge._parse_ping_command("/ping") == ""

    def test_not_a_ping(self, bridge):
        assert bridge._parse_ping_command("/nb bind setup") is None

    def test_plain_text(self, bridge):
        assert bridge._parse_ping_command("hello world") is None

    def test_ping_with_instance_suffix(self, bridge):
        assert bridge._parse_ping_command("/ping@bot RhenCloud") == "RhenCloud"


class TestParseInternalCommand:
    def test_valid_command(self, bridge):
        result = bridge._parse_internal_command("/nb bind setup")
        assert result == ("bind", ["setup"])

    def test_command_with_multiple_args(self, bridge):
        result = bridge._parse_internal_command("/nb bind confirm 123456")
        assert result == ("bind", ["confirm", "123456"])

    def test_no_slash(self, bridge):
        assert bridge._parse_internal_command("hello") is None

    def test_wrong_prefix(self, bridge):
        assert bridge._parse_internal_command("/xx bind setup") is None

    def test_no_action(self, bridge):
        result = bridge._parse_internal_command("/nb")
        assert result == ("", [])

    def test_custom_prefix(self, bridge):
        bridge.command_prefix = "bot"
        result = bridge._parse_internal_command("/bot bind setup")
        assert result == ("bind", ["setup"])

    def test_with_instance_suffix(self, bridge):
        result = bridge._parse_internal_command("/nb@bot bind setup")
        assert result == ("bind", ["setup"])


class TestMatchesChannel:
    def test_matches(self, bridge):
        msg = NormalizedMessage(
            instance_id="inst1", channel={"id": "ch1", "type": "group"}
        )
        channels = {"inst1": {"id": "ch1", "type": "group"}}
        assert bridge._matches_channel(msg, channels)

    def test_no_match_instance(self, bridge):
        msg = NormalizedMessage(instance_id="inst2", channel={"id": "ch1"})
        channels = {"inst1": {"id": "ch1"}}
        assert not bridge._matches_channel(msg, channels)

    def test_matches_with_extra_rule_keys(self, bridge):
        msg = NormalizedMessage(instance_id="inst1", channel={"id": "ch1"})
        channels = {
            "inst1": {
                "id": "ch1",
                "msg": {"msg_format": "custom"},
                "webhook_url": "https://hook",
            }
        }
        assert bridge._matches_channel(msg, channels)

    def test_partial_channel_match(self, bridge):
        msg = NormalizedMessage(instance_id="inst1", channel={"id": "ch1"})
        channels = {"inst1": {"id": "ch1", "type": "group"}}
        assert bridge._matches_channel(msg, channels)

    def test_mismatch_value(self, bridge):
        msg = NormalizedMessage(instance_id="inst1", channel={"id": "ch1"})
        channels = {"inst1": {"id": "ch2"}}
        assert not bridge._matches_channel(msg, channels)


class TestMatchesFrom:
    def test_matches(self, bridge):
        msg = NormalizedMessage(instance_id="inst1", channel={"id": "ch1"})
        from_cfg = {"inst1": {"id": "ch1"}}
        assert bridge._matches_from(msg, from_cfg)

    def test_no_match_instance(self, bridge):
        msg = NormalizedMessage(instance_id="inst1", channel={"id": "ch1"})
        from_cfg = {"inst2": {"id": "ch1"}}
        assert not bridge._matches_from(msg, from_cfg)

    def test_no_match_value(self, bridge):
        msg = NormalizedMessage(instance_id="inst1", channel={"id": "ch1"})
        from_cfg = {"inst1": {"id": "ch2"}}
        assert not bridge._matches_from(msg, from_cfg)

    def test_partial_match(self, bridge):
        msg = NormalizedMessage(instance_id="inst1", channel={"id": "ch1"})
        from_cfg = {"inst1": {"id": "ch1", "type": "group"}}
        assert bridge._matches_from(msg, from_cfg)

    def test_string_vs_int_matching(self, bridge):
        msg = NormalizedMessage(instance_id="inst1", channel={"id": 123})
        from_cfg = {"inst1": {"id": "123"}}
        assert bridge._matches_from(msg, from_cfg)


class TestIsAllowedCommandSource:
    def test_connect_rule_matches(self, bridge):
        bridge._rules = [
            {"id": "r1", "type": "connect", "channels": {"inst1": {"id": "ch1"}}}
        ]
        msg = NormalizedMessage(instance_id="inst1", channel={"id": "ch1"})
        assert bridge._is_allowed_command_source(msg)

    def test_forward_rule_matches(self, bridge):
        bridge._rules = [
            {
                "id": "r1",
                "type": "forward",
                "from": {"inst1": {"id": "ch1"}},
                "to": {"inst2": {"id": "ch2"}},
            }
        ]
        msg = NormalizedMessage(instance_id="inst1", channel={"id": "ch1"})
        assert bridge._is_allowed_command_source(msg)

    def test_no_match(self, bridge):
        bridge._rules = [
            {"id": "r1", "type": "connect", "channels": {"inst1": {"id": "ch1"}}}
        ]
        msg = NormalizedMessage(instance_id="inst2", channel={"id": "ch2"})
        assert not bridge._is_allowed_command_source(msg)

    def test_empty_rules(self, bridge):
        bridge._rules = []
        msg = NormalizedMessage(instance_id="inst1", channel={"id": "ch1"})
        assert not bridge._is_allowed_command_source(msg)


class TestBuildFormatted:
    def test_default_format(self, bridge):
        msg = NormalizedMessage(
            platform="discord",
            instance_id="discord_main",
            channel={"id": "123"},
            nickname="Alice",
            user_id="user1",
            text="Hello",
            username="alice",
        )
        formatted, extra = bridge._build_formatted(msg, {})
        assert "Hello" in formatted
        assert extra["user_id"] == "user1"
        assert extra["msg"] == "Hello"

    def test_custom_msg_format(self, bridge):
        msg = NormalizedMessage(text="Hello", user_id="u1")
        formatted, _ = bridge._build_formatted(msg, {"msg_format": "{msg}"})
        assert formatted == "Hello"

    def test_webhook_format(self, bridge):
        msg = NormalizedMessage(text="Hello", user_id="u1")
        formatted, _ = bridge._build_formatted(
            msg,
            {"webhook_msg_format": "webhook: {msg}", "bot_msg_format": "bot: {msg}"},
            is_webhook=True,
        )
        assert formatted == "webhook: Hello"

    def test_bot_format(self, bridge):
        msg = NormalizedMessage(text="Hello", user_id="u1")
        formatted, _ = bridge._build_formatted(
            msg,
            {"webhook_msg_format": "webhook: {msg}", "bot_msg_format": "bot: {msg}"},
            is_webhook=False,
        )
        assert formatted == "bot: Hello"

    def test_missing_format_key_fallback(self, bridge):
        msg = NormalizedMessage(text="Hello")
        formatted, _ = bridge._build_formatted(msg, {"msg_format": "{missing_key}"})
        assert formatted == "Hello"


class TestNormalizeTargetCqface:
    def test_discord_passthrough(self, bridge):
        text, extra = bridge._normalize_target_cqface("discord", "hello", {})
        assert text == "hello"

    def test_non_discord_calls_replace(self, bridge):
        with patch(
            "services.bridge.cqface.replace_cqface_tokens", return_value="replaced"
        ) as mock:
            with patch(
                "services.bridge.cqface.replace_cqface_tokens_in_obj", return_value=({})
            ) as mock2:
                text, extra = bridge._normalize_target_cqface("telegram", "hello", {})
                mock.assert_called_once_with("hello")
                mock2.assert_called_once_with({})

    def test_none_platform(self, bridge):
        with patch(
            "services.bridge.cqface.replace_cqface_tokens", return_value="replaced"
        ) as mock:
            with patch(
                "services.bridge.cqface.replace_cqface_tokens_in_obj", return_value=({})
            ):
                text, extra = bridge._normalize_target_cqface(None, "hello", {})
                mock.assert_called_once_with("hello")


class TestLoadSensitiveValues:
    def test_loads_from_config(self, bridge):
        config = {"bot": {"token": "secret123"}}
        bridge.load_sensitive_values(config)
        assert "secret123" in bridge._sensitive

    def test_empty_config(self, bridge):
        bridge.load_sensitive_values({})
        assert bridge._sensitive == frozenset()


class TestRegisterSender:
    def test_registers_sender(self, bridge):
        async def fake_send(channel, text, **kwargs):
            pass

        bridge.register_sender("inst1", fake_send)
        assert "inst1" in bridge._senders
        assert bridge._senders["inst1"][1] is fake_send

    def test_senders_snapshot(self, bridge):
        async def fake_send(channel, text, **kwargs):
            pass

        bridge.register_sender("inst1", fake_send)
        snapshot = bridge.senders_snapshot()
        assert snapshot == [{"instance_id": "inst1", "platform": None}]


class TestDispatchContinueOnError:
    """核心: 单个目标发送失败不应该中断后续目标 (issue #1)"""

    @pytest.mark.asyncio
    async def test_forward_dispatch_continues_after_sender_error(self, bridge):
        msg = NormalizedMessage(
            instance_id="src", channel={"id": "ch_src"}, text="hello"
        )
        mock_sender1 = AsyncMock(side_effect=Exception("boom"))
        mock_sender2 = AsyncMock(return_value="msg002")
        mock_sender3 = AsyncMock(return_value="msg003")

        bridge._senders = {
            "target1": ("p1", mock_sender1),
            "target2": ("p2", mock_sender2),
            "target3": ("p3", mock_sender3),
        }
        bridge._sensitive = frozenset()
        bridge._middleware = None

        rule = {
            "id": "rule1",
            "type": "forward",
            "to": {
                "target1": {"id": "ch1"},
                "target2": {"id": "ch2"},
                "target3": {"id": "ch3"},
            },
            "msg": {},
        }

        with patch("services.bridge.msg_db") as mock_msg_db:
            mock_db = MagicMock()
            mock_db.get_platform_msg_id.return_value = None
            mock_db.get_bound_user_id.return_value = None
            mock_msg_db.return_value = mock_db

            await bridge._dispatch(msg, rule, "bridge1")

        mock_sender1.assert_awaited_once()
        mock_sender2.assert_awaited_once()
        mock_sender3.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_dispatch_continues_after_sender_error(self, bridge):
        """_dispatch_connect 的回归测试: return -> continue 修复验证"""
        msg = NormalizedMessage(
            instance_id="src", channel={"id": "ch_src"}, text="hello"
        )

        mock_sender1 = AsyncMock(side_effect=Exception("boom"))
        mock_sender2 = AsyncMock(return_value="msg002")
        mock_sender3 = AsyncMock(return_value="msg003")

        bridge._senders = {
            "target1": ("p1", mock_sender1),
            "target2": ("p2", mock_sender2),
            "target3": ("p3", mock_sender3),
        }
        bridge._sensitive = frozenset()
        bridge._middleware = None

        rule = {
            "id": "rule1",
            "type": "connect",
            "channels": {
                "target1": {"id": "ch1"},
                "target2": {"id": "ch2"},
                "target3": {"id": "ch3"},
            },
            "msg": {},
        }

        with patch("services.bridge.msg_db") as mock_msg_db:
            mock_db = MagicMock()
            mock_db.get_platform_msg_id.return_value = None
            mock_db.get_bound_user_id.return_value = None
            mock_msg_db.return_value = mock_db

            await bridge._dispatch_connect(msg, rule, "bridge1")

        mock_sender1.assert_awaited_once()
        mock_sender2.assert_awaited_once()
        mock_sender3.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_skips_echo_and_missing_sender(self, bridge):
        """验证 echo skip 和 missing sender 不会中断后续目标"""
        msg = NormalizedMessage(
            instance_id="target1", channel={"id": "ch1"}, text="hello"
        )
        mock_sender2 = AsyncMock(return_value="msg002")
        mock_sender3 = AsyncMock(return_value="msg003")

        bridge._senders = {
            "target2": ("p2", mock_sender2),
            "target3": ("p3", mock_sender3),
        }
        bridge._sensitive = frozenset()
        bridge._middleware = None

        rule = {
            "id": "rule1",
            "type": "forward",
            "to": {
                "target1": {"id": "ch1"},  # echo skip (same instance)
                "target2": {"id": "ch2"},  # no sender registered
                "target3": {"id": "ch3"},  # ok
            },
            "msg": {},
        }

        with patch("services.bridge.msg_db") as mock_msg_db:
            mock_db = MagicMock()
            mock_db.get_platform_msg_id.return_value = None
            mock_db.get_bound_user_id.return_value = None
            mock_msg_db.return_value = mock_db

            await bridge._dispatch(msg, rule, "bridge1")

        mock_sender2.assert_awaited_once()
        mock_sender3.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_all_targets_when_formatted_sensitive(self, bridge):
        """验证敏感内容拦截会跳过所有目标 (forward 共用格式化输出)"""
        msg = NormalizedMessage(
            instance_id="src", channel={"id": "ch_src"}, text="my token is abc123"
        )
        mock_sender = AsyncMock(return_value="msg002")

        bridge._senders = {
            "target1": ("p1", mock_sender),
            "target2": ("p2", mock_sender),
        }
        bridge._sensitive = frozenset(["abc123"])
        bridge._middleware = None

        rule = {
            "id": "rule1",
            "type": "forward",
            "to": {"target1": {"id": "ch1"}, "target2": {"id": "ch2"}},
            "msg": {},
        }

        with patch("services.bridge.msg_db") as mock_msg_db:
            mock_db = MagicMock()
            mock_db.get_platform_msg_id.return_value = None
            mock_db.get_bound_user_id.return_value = None
            mock_msg_db.return_value = mock_db

            await bridge._dispatch(msg, rule, "bridge1")

        mock_sender.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_connect_dispatch_cancelled_error_continues(self, bridge):
        """验证 CancelledError 在 connect 中也会被捕获并继续"""
        msg = NormalizedMessage(
            instance_id="src", channel={"id": "ch_src"}, text="hello"
        )
        mock_sender1 = AsyncMock(side_effect=asyncio.CancelledError())
        mock_sender2 = AsyncMock(return_value="msg002")

        bridge._senders = {
            "target1": ("p1", mock_sender1),
            "target2": ("p2", mock_sender2),
        }
        bridge._sensitive = frozenset()
        bridge._middleware = None

        rule = {
            "id": "rule1",
            "type": "connect",
            "channels": {"target1": {"id": "ch1"}, "target2": {"id": "ch2"}},
            "msg": {},
        }

        with patch("services.bridge.msg_db") as mock_msg_db:
            mock_db = MagicMock()
            mock_db.get_platform_msg_id.return_value = None
            mock_db.get_bound_user_id.return_value = None
            mock_msg_db.return_value = mock_db

            await bridge._dispatch_connect(msg, rule, "bridge1")

        mock_sender1.assert_awaited_once()
        mock_sender2.assert_awaited_once()
