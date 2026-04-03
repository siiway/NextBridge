> This document was written by AI and has been manually reviewed.

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
| `max_file_size` | No | `8388608` (8 MB) | Maximum bytes per attachment when sending |
| `send_as_bot_when_using_cqface_emoji` | No | `false` | When `true`, messages containing `:cqface<id>:` tokens (emitted by the NapCat driver's `cqface_mode: "emoji"`) are sent via the bot instead of the webhook, even if `send_method` is `"webhook"`. Requires `bot_token`. |
| `send_replies_as_bot` | No | `true` | When `true`, reply messages are sent via the bot (if connected) even when `send_method` is `"webhook"`, because Discord webhook mode does not support specifying a reply target message. Requires `bot_token` to take effect. |
| `allow_mentions_everyone` | No | `false` | Controls whether outgoing messages can trigger `@everyone` / `@here` mentions on Discord. |
| `allow_mentions_users` | No | `true` | Controls whether outgoing messages can mention users (`<@id>`). |
| `allow_mentions_roles` | No | `false` | Controls whether outgoing messages can mention roles (`<@&id>`). |
| `sanitize_mass_mentions` | No | `true` | When `true`, outgoing plain text `@everyone` / `@here` is neutralized to avoid mass pings. |
| `proxy` | No | — | Proxy URL for all Discord API requests (e.g., `http://proxy.example.com:8080` or `socks5://proxy.example.com:1080`). When set, SSL verification is disabled for the proxy connection. Set to `null` to explicitly disable proxy for this instance (ignores global proxy setting). |

\* For receiving messages, `bot_token` must be provided. For webhook-only sending, only `webhook_url` in rules is required.

```json
{
  "discord": {
    "dc_main": {
      "bot_token": "your_bot_token",
      "send_method": "webhook",
      "max_file_size": 8388608,
      "allow_mentions_everyone": false,
      "allow_mentions_users": true,
      "allow_mentions_roles": false,
      "sanitize_mass_mentions": true,
      "proxy": "http://proxy.example.com:8080"
    }
  }
}
```

## Send modes

### webhook (default)

Sends via a Discord webhook URL. Supports a custom display name and avatar per message, set via the `webhook_title` and `webhook_avatar` keys in the rule's `msg` config.

Note: Discord webhook mode does not support specifying a reply target message. If you need bridged replies to render as Discord replies, enable `send_replies_as_bot` and provide `bot_token`.

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
| `webhook_url` | Webhook URL for this channel (required when using webhook send mode) |

```json
{
  "dc_main": {
    "server_id": "1061629481267245086",
    "channel_id": "1269706305661309030",
    "webhook_url": "https://discord.com/api/webhooks/ID/TOKEN"
  }
}
```

## Extra msg keys

These can be placed in the rule's `msg` block and are picked up by the Discord driver:

| Key | Description |
|---|---|
| `webhook_msg_format` | Overrides `msg_format` when the message is sent via webhook. Supports the same template variables. |
| `bot_msg_format` | Overrides `msg_format` when the message is sent via the bot (including when `send_as_bot_when_using_cqface_emoji` or `send_replies_as_bot` triggers). Supports the same template variables. |
| `webhook_title` | Display name shown on the webhook message (`send_method: "webhook"` only) |
| `webhook_avatar` | Avatar URL shown on the webhook message (`send_method: "webhook"` only) |

All keys support the same template variables as `msg_format`.

## CQ Face Emojis (discord_emojis.json)

When using NapCat's `cqface_mode: "emoji"`, the Discord driver resolves `:cqface<id>:` tokens to Discord custom emojis (`<:cqface306:emoji_id>`) using a local JSON file. To set this up:

1. Go to `https://discord.com/developers/applications/<your_app_id>/emojis` in your browser.
2. Open the browser **Network** tab (F12 → Network).
3. Refresh the page.
4. Find the request to the `emojis` endpoint (e.g. `https://discord.com/api/v9/applications/1343923133370994750/emojis`).
5. Copy the JSON response body and save it as `discord_emojis.json` in the data directory (default: `data/discord_emojis.json`).

If the file is absent or an emoji is not found, the token falls back to the plain `:cqface<id>:` text.

## Notes

- Bot messages are automatically ignored (webhook echoes are not re-bridged).
- Files are downloaded and re-uploaded via multipart form. If a file exceeds `max_file_size`, its URL is appended to the message text.
