# Discord

The Discord driver receives messages through the Discord gateway (bot token) and can send via either a **webhook** or the bot itself.

## Setup

1. Create a bot at the [Discord Developer Portal](https://discord.com/developers/applications).
2. Under **Bot**, enable the **Message Content Intent**.
3. Copy the bot token.
4. For webhook sending: create a webhook in your channel's settings and copy its URL.
5. Invite the bot to your server with at least `Read Messages` and `Send Messages` permissions.

## Config keys

Add under `discord.<instance_id>` in `config.json`:

| Key | Required | Default | Description |
|---|---|---|---|
| `bot_token` | No* | — | Discord bot token. Required for receiving messages and for `bot` send mode |
| `send_method` | No | `webhook` | `"webhook"` or `"bot"` |
| `webhook_url` | No* | — | Webhook URL. Required when `send_method` is `"webhook"` |
| `max_file_size` | No | `8388608` (8 MB) | Maximum bytes per attachment when sending |

\* At least one of `bot_token` (for receive) or `webhook_url` (for send) must be provided.

```json
{
  "discord": {
    "dc_main": {
      "bot_token": "your_bot_token",
      "send_method": "webhook",
      "webhook_url": "https://discord.com/api/webhooks/ID/TOKEN",
      "max_file_size": 8388608
    }
  }
}
```

## Send modes

### webhook (default)

Sends via a Discord webhook URL. Supports a custom display name and avatar per message, set via the `webhook_title` and `webhook_avatar` keys in the rule's `msg` config.

```json
"msg": {
  "msg_format": "{msg}",
  "webhook_title": "{user} @ {from}",
  "webhook_avatar": "{user_avatar}"
}
```

### bot

Sends via the bot itself. Requires `bot_token`. Does not support per-message username/avatar.

## Rule channel keys

Use under `channels` or `from`/`to` in `rules.json`:

| Key | Description |
|---|---|
| `server_id` | Discord guild (server) ID |
| `channel_id` | Discord channel ID |

```json
{
  "dc_main": {
    "server_id": "1061629481267245086",
    "channel_id": "1269706305661309030"
  }
}
```

## Extra msg keys

These can be placed in the rule's `msg` block and are only used by the Discord driver when `send_method` is `"webhook"`:

| Key | Description |
|---|---|
| `webhook_title` | Display name shown on the webhook message |
| `webhook_avatar` | Avatar URL shown on the webhook message |

Both support the same template variables as `msg_format`.

## Notes

- Bot messages are automatically ignored (webhook echoes are not re-bridged).
- Files are downloaded and re-uploaded via multipart form. If a file exceeds `max_file_size`, its URL is appended to the message text.
