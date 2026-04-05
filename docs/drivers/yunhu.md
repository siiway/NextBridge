> This document was written by AI and has been manually reviewed.

# Yunhu (云湖)

The Yunhu driver receives messages via a webhook HTTP server and sends via the Yunhu open API.

## Setup

1. Go to the [Yunhu control console](https://www.yhchat.com/control) and create a bot.
2. Copy the bot token.
3. Set the bot's webhook URL to `http://<your-server>:<global.http.port><webhook_path>` (e.g. `http://1.2.3.4:9080/yunhu-webhook`).
4. In Event Subscription, enable "Normal message event" (without it, webhook cannot receive regular chat messages).
5. Add the bot to your group.
6. Note the group's chat ID (visible in the group settings or in an incoming webhook event's `message.chatId` field).

## Config keys

Add under `yunhu.<instance_id>` in `config.json`:

| Key | Required | Default | Description |
|---|---|---|---|
| `token` | Yes | — | Bot token from the Yunhu control console |
| `webhook_path` | No | `"/yunhu-webhook"` | HTTP path for the webhook endpoint |
| `proxy_host` | No | `"https://yh-proxy.siiway.top"` | Base URL of the `cloudflare/yh-proxy.js` Worker. Enables two sub-features: avatar URLs are rewritten to `<host>/pfp?url=...` (adds required Referer); Discord CDN attachment URLs are rewritten to `<host>/media?url=...` so Yunhu's servers can fetch them from within China Mainland. |
| `proxy` | No | — | Proxy URL for all Yunhu API requests (e.g., `http://proxy.example.com:8080` or `socks5://proxy.example.com:1080`). Set to `null` to explicitly disable proxy for this instance (ignores global proxy setting). |

::: tip Public endpoint available
`https://yh-proxy.siiway.top` is a hosted instance of `cloudflare/yh-proxy.js` that you can use directly without deploying your own Worker.
:::

```json
{
  "yunhu": {
    "yh_main": {
      "token": "your-yunhu-bot-token",
      "webhook_path": "/yunhu-webhook",
      "proxy_host": "https://yh-proxy.siiway.top"
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
| `file` | — (receive not supported) |

## Sending

Each outgoing message is split into one or more Yunhu API calls:

| Attachment type | Yunhu content type | Notes |
|---|---|---|
| `image` | `image` | Yunhu fetches the URL server-side and renders an inline image |
| `video` | `video` | Rendered as an inline video player |
| `voice` / `file` | `file` | Rendered as a downloadable file link |
| (no URL) | `text` | A `[Type: filename]` text fallback is appended to the text message |

The text portion (including any rich-header prefix) is sent first, then each attachment as a separate message.

> Note: here `Receive` means messages entering NextBridge; `Send` means NextBridge sending messages to Yunhu via the open API. Yunhu does not support file messages as received attachments, but it can send files normally.

## Notes

- Yunhu must be able to reach the webhook URL from the internet. When running behind NAT, use a reverse proxy or a tunnel such as `ngrok / Cloudflare Tunnel`.
- Multiple Yunhu instances can share the same process and port. Use different `webhook_path` values per instance.
- The bot token is sent as a query parameter (`?token=...`) on every outgoing request — keep it secret.
