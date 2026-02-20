# KOOK (开黑啦)

The KOOK driver uses [khl-py](https://github.com/TWT233/khl.py) to connect via WebSocket (bot mode). It receives TEXT and KMarkdown messages from public text channels and sends using the KOOK bot API.

## Setup

1. Go to the [KOOK developer portal](https://developer.kookapp.cn/) and create a bot application.
2. Under **机器人** → **机器人连接方式**, select **WebSocket**.
3. Copy the bot token.
4. Invite the bot to your server and give it permission to read and send messages in the target channel.
5. Get the channel ID (right-click the channel → Copy ID, or from the channel URL).

## Config keys

Add under `kook.<instance_id>` in `config.json`:

| Key | Required | Default | Description |
|---|---|---|---|
| `token` | Yes | — | Bot token from the KOOK developer portal |
| `max_file_size` | No | `26214400` (25 MB) | Maximum bytes per attachment when uploading |

```json
{
  "kook": {
    "kook_main": {
      "token": "your-kook-bot-token",
      "max_file_size": 26214400
    }
  }
}
```

## Rule channel keys

Use under `channels` or `from`/`to` in `rules.json`:

| Key | Description |
|---|---|
| `channel_id` | KOOK text channel ID |

```json
{
  "kook_main": { "channel_id": "1234567890123456" }
}
```

## Received message types

TEXT and KMarkdown messages from public text channels are bridged. The raw message content (including any KMarkdown syntax) is passed through as the message text.

## Sending

| Attachment type | Sent as |
|---|---|
| `image` | Uploaded to KOOK CDN; embedded with `(img)url(img)` KMarkdown syntax |
| `voice` / `video` / `file` | Uploaded to KOOK CDN; sent as a `[filename](url)` hyperlink |

When the message contains images or a rich header, the message is sent as `KMarkdown` type so formatting renders correctly. Plain text messages with no attachments are sent as `TEXT` type.

## Notes

- The bot must be in the target server before NextBridge starts.
- Incoming KMarkdown messages are forwarded as-is. Other platforms may see raw KMarkdown syntax (e.g. `**bold**`) as plain text.
- The KOOK WebSocket connection reconnects automatically if the khl-py library handles it internally.
