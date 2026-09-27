from drivers.discord import build_native_command_text, resolve_native_command_name


class TestBuildNativeCommandText:
    def test_bind_setup(self):
        assert build_native_command_text("nb", "bind", "setup") == "/nb bind setup"

    def test_bind_confirm(self):
        assert (
            build_native_command_text("nb", "bind", "confirm", "123456")
            == "/nb bind confirm 123456"
        )

    def test_bind_rm_without_target(self):
        assert build_native_command_text("nb", "bind", "rm", None) == "/nb bind rm"

    def test_bind_rm_with_target(self):
        assert build_native_command_text("nb", "bind", "rm", "qq") == "/nb bind rm qq"

    def test_bind_list(self):
        assert build_native_command_text("nb", "bind", "list") == "/nb bind list"

    def test_notify_mode(self):
        assert (
            build_native_command_text("nb", "notify", "mode", "whitelist")
            == "/nb notify mode whitelist"
        )

    def test_notify_add(self):
        assert (
            build_native_command_text("nb", "notify", "add", "telegram")
            == "/nb notify add telegram"
        )

    def test_status_and_help(self):
        assert build_native_command_text("nb", "status") == "/nb status"
        assert build_native_command_text("nb", "help") == "/nb help"

    def test_custom_prefix_is_preserved(self):
        assert build_native_command_text("!", "status") == "/! status"

    def test_empty_parts_are_skipped(self):
        assert build_native_command_text("nb", "bind", "", None) == "/nb bind"


class TestResolveNativeCommandName:
    def test_default(self):
        assert resolve_native_command_name("nb") == "nb"

    def test_lowercased(self):
        assert resolve_native_command_name("NB") == "nb"

    def test_leading_slash_stripped(self):
        assert resolve_native_command_name("/nb") == "nb"

    def test_empty_falls_back(self):
        assert resolve_native_command_name("") == "nb"

    def test_non_ascii_falls_back(self):
        assert resolve_native_command_name("桥接") == "nb"

    def test_spaces_fall_back(self):
        assert resolve_native_command_name("my cp") == "nb"

    def test_too_long_falls_back(self):
        assert resolve_native_command_name("a" * 33) == "nb"

    def test_allowed_symbols(self):
        assert resolve_native_command_name("nb-cmd_1") == "nb-cmd_1"
