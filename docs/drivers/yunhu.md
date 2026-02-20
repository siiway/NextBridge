# Yunhu (云湖)

The Yunhu driver receives messages via a webhook HTTP server and sends via the Yunhu open API.

## Setup

1. Go to the [Yunhu developer portal](https://www.yunhuim.com/) and create a bot.
2. Copy the bot token.
3. Set the bot's webhook URL to `http://<your-server>:<webhook_port><webhook_path>` (e.g. `http://1.2.3.4:8765/yunhu-webhook`).
4. Add the bot to your group.
5. Note the group's chat ID (visible in the group settings or in an incoming webhook event's `message.chatId` field).

## Config keys

Add under `yunhu.<instance_id>` in `config.json`:

| Key | Required | Default | Description |
|---|---|---|---|
| `token` | Yes | — | Bot token from the Yunhu developer portal |
| `webhook_port` | No | `8765` | Port for the incoming webhook HTTP server |
| `webhook_path` | No | `"/yunhu-webhook"` | HTTP path for the webhook endpoint |
| `proxy_host` | No | — | Base URL of the `cloudflare/yh-proxy.js` Worker. Enables two sub-features: avatar URLs are rewritten to `<host>/pfp?url=…` (adds required Referer); Discord CDN attachment URLs are rewritten to `<host>/media?url=…` so Yunhu's servers can fetch them from inside China. |

```json
{
  "yunhu": {
    "yh_main": {
      "token": "your-yunhu-bot-token",
      "webhook_port": 8765,
      "webhook_path": "/yunhu-webhook",
      "proxy_host": "https://proxy.yourname.workers.dev"
    }
  }
}
```

## Rule channel keys

Use under `channels` or `from`/`to` in `rules.json`:

| Key | Description |
|---|---|
| `chat_id` | Yunhu group (or user) chat ID |
| `chat_type` | `"group"` (default) or `"user"` |

```json
{
  "yh_main": { "chat_id": "your-group-chat-id", "chat_type": "group" }
}
```

## Received message types

| Yunhu content type | Attachment type |
|---|---|
| `text` / `markdown` | — (plain text) |
| `image` | `image` |
| `video` | `video` |
| `file` | `file` |

## Sending

Each outgoing message is split into one or more Yunhu API calls:

| Attachment type | Yunhu content type | Notes |
|---|---|---|
| `image` | `image` | Yunhu fetches the URL server-side and renders an inline image |
| `video` | `video` | Rendered as an inline video player |
| `voice` / `file` | `file` | Rendered as a downloadable file link |
| (no URL) | `text` | A `[Type: filename]` text fallback is appended to the text message |

The text portion (including any rich-header prefix) is sent first, then each attachment as a separate message.

## Notes

- Yunhu must be able to reach the webhook URL from the internet. When running behind NAT, use a reverse proxy or a tunnel such as `ngrok`.
- Each NextBridge instance binds a single port. If you have multiple Yunhu instances, give each a different `webhook_port`.
- The bot token is sent as a query parameter (`?token=…`) on every outgoing request — keep it secret.
