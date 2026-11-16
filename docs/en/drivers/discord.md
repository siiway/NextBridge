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
| `cqface_webhook_fallback` | No | `"unicode"` | How to render CQ face tokens when sending via webhook. `"bot"` sends via bot when CQ face tokens are present; `"unicode"` renders as unicode emoji fallback. |
| `send_replies_as_bot` | No | `true` | When `true`, reply messages are sent via the bot (if connected) even when `send_method` is `"webhook"`, because Discord webhook mode does not support specifying a reply target message. Requires `bot_token` to take effect. |
| `allow_mentions_everyone` | No | `false` | Allow `@everyone`/`@here` mentions in bridged messages |
| `allow_mentions_users` | No | `true` | Allow `@user` mentions in bridged messages |
| `allow_mentions_roles` | No | `false` | Allow `@role` mentions in bridged messages |
| `sanitize_mass_mentions` | No | `true` | Neutralize `@everyone`/`@here` in outgoing message text (replaces with plain text) |
| `auto_link_image_hosts` | No | `["discordmedia.com", "tenor.com"]` | Host allowlist for receiving messages that contain only one URL. When the host matches, NextBridge tries to resolve the URL to an image and bridges it as an image attachment. Subdomains are included. Set to `[]` to disable. |
| `auto_link_image_show_original_url` | No | `true` | When auto link-to-image succeeds, keep the original URL before the image. Set to `false` to bridge only the resolved image. |
| `enable_recall` | No | `true` | Whether to sync message recalls. When enabled, deletions on Discord are detected and bridged to other platforms, and recalls from other platforms are applied to Discord. Set to `false` to disable recall sync. |
| `media_proxy` | No | — | Proxy URL used only when fetching media/attachments. Defaults to following `proxy` when unset. |
| `proxy` | No | — | Proxy URL for all Discord API requests (e.g., `http://proxy.example.com:8080` or `socks5://proxy.example.com:1080`). When set, SSL verification is disabled for the proxy connection. Set to `null` to explicitly disable proxy for this instance (ignores global proxy setting). |

\* For receiving messages, `bot_token` must be provided. For webhook-only sending, only `webhook_url` in rules is required.

```json
{
  "discord": {
    "dc_main": {
      "bot_token": "your_bot_token",
      "send_method": "webhook",
      "max_file_size": 8388608,
      "auto_link_image_hosts": ["discordmedia.com", "tenor.com"],
      "auto_link_image_show_original_url": true,
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
| `bot_msg_format` | Overrides `msg_format` when the message is sent via the bot (including when `cqface_webhook_fallback` or `send_replies_as_bot` triggers). Supports the same template variables. |
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

## Message Edit Sync

When a Discord message is edited, NextBridge detects the change and updates the corresponding bridged messages on other platforms.

**Requirements:**
- `bot_token` must be configured to receive edit events from Discord.
- Webhook-only mode (no `bot_token`) cannot receive edit events; edits from other platforms can still be applied to Discord.

**How edits are applied to Discord:**
- If `webhook_url` is configured for the channel, NextBridge uses the Discord webhook edit API (`PATCH /webhooks/{id}/{token}/messages/{message_id}`).
- Otherwise, if `bot_token` is available, the bot fetches and edits the message directly.

Only text content is synced on edit. Attachments are not modified.

Edit sync is only triggered when the message's visible content (text or attachments) actually changes. Actions such as **pinning a message** or **an auto-generated link preview (embed)** do not change the text, so they are not mistaken for edits and are not synced to other platforms.

## Message Recall Sync

When a Discord message is deleted, NextBridge detects the deletion and removes the corresponding bridged messages on other platforms.

**Requirements:**
- `bot_token` must be configured to detect deletions from Discord (detected via the gateway raw delete event, which catches even uncached messages).
- Webhook-only mode (no `bot_token`) cannot detect deletions on Discord; recalls from other platforms can still be applied to Discord.

**How recalls are applied to Discord:**
- If `webhook_url` is configured for the channel, NextBridge uses the Discord webhook delete API (`DELETE /webhooks/{id}/{token}/messages/{message_id}`).
- Otherwise, if `bot_token` is available, the bot fetches and deletes the message directly.

Set `enable_recall` to `false` to disable both detection and application of recalls.

## Sticker & Custom Emoji Bridging

Discord stickers and custom emojis are automatically converted to images/GIFs and bridged to other platforms as attachments.

| Type | Format | Bridging Method |
|---|---|---|
| Sticker | PNG / APNG | Sent as `image` attachment, using the sticker CDN URL |
| Sticker | GIF | Sent as `image` attachment (GIF) |
| Sticker | Lottie | Not directly bridgeable as an image; uses text `[Sticker: name]` as fallback |
| Custom Emoji | Static (`<:name:id>`) | Sent as `image` attachment (PNG), downloaded from Discord CDN |
| Custom Emoji | Animated (`<a:name:id>`) | Sent as `image` attachment (GIF), downloaded from Discord CDN |

No additional configuration is needed. All stickers and custom emojis are automatically handled when received via `bot_token`.

## Notes

- Bot messages are automatically ignored (webhook echoes are not re-bridged). Mass mentions (`@everyone`/`@here`) are sanitized by default.
- Messages that contain only one URL from `auto_link_image_hosts` are resolved like the Discord client preview path. Direct image URLs are bridged as images; HTML pages are scanned for `og:image`/`twitter:image`. If resolving fails, the original text is bridged unchanged.
- Files are downloaded and re-uploaded via multipart form. If a file exceeds `max_file_size`, its URL is appended to the message text.
