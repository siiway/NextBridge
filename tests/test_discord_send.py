from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from drivers.discord import DiscordConfig, DiscordDriver


@pytest.mark.asyncio
async def test_webhook_send_applies_webhook_format():
    driver = DiscordDriver(
        "discord_test",
        DiscordConfig(send_method="webhook", proxy=None),
        MagicMock(),
    )
    channel = {"id": "123", "webhook_url": "https://example.invalid/webhook"}

    with (
        patch.object(driver, "_send_webhook", new_callable=AsyncMock) as webhook_send,
        patch.object(driver, "_send_bot", new_callable=AsyncMock) as bot_send,
    ):
        await driver.send(
            channel,
            "bot: Hello",
            msg="Hello",
            webhook_msg_format="webhook: {msg}",
            bot_msg_format="bot: {msg}",
        )

    webhook_send.assert_awaited_once()
    assert webhook_send.await_args is not None
    assert webhook_send.await_args.args[1] == "webhook: Hello"
    bot_send.assert_not_awaited()
