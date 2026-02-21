# NapCat (QQ)

NextBridge connects to [NapCat](https://napneko.github.io) — an unofficial QQ client that exposes the OneBot 11 WebSocket API. There is no official QQ bot API for regular accounts, so NapCat is used as the bridge layer.

## Setup

1. Install and run NapCat, configured as a WebSocket server.
2. Note the WebSocket URL (default: `ws://127.0.0.1:3001`) and any access token you configured.
3. Add the instance to `data/config.json`.

## Config keys

Add under `napcat.<instance_id>` in `config.json`:

| Key | Required | Default | Description |
|---|---|---|---|
| `ws_url` | No | `ws://127.0.0.1:3001` | WebSocket URL of the NapCat server |
| `ws_token` | No | — | Access token (appended as `?access_token=…`) |
| `max_file_size` | No | `10485760` (10 MB) | Maximum bytes to download per attachment when sending |
| `cqface_mode` | No | `"gif"` | How to represent QQ face/emoji segments. `"gif"` uploads the face as an animated GIF (from the local `db/cqface-gif/` database); `"emoji"` renders it as inline text, e.g. `:cqface306:`. |
| `file_send_mode` | No | `"stream"` | How to upload files and videos to QQ. `"stream"` uses chunked `upload_file_stream` (recommended for large files); `"base64"` encodes the whole payload and passes it directly to `upload_group_file`. |
| `stream_threshold` | No | `0` (disabled) | If greater than 0, automatically switches to `"stream"` mode when a file or video exceeds this many bytes, regardless of `file_send_mode`. |

```json
{
  "napcat": {
    "qq_main": {
      "ws_url": "ws://127.0.0.1:3001",
      "ws_token": "your_secret",
      "max_file_size": 10485760
    }
  }
}
```

## Rule channel keys

Use under `channels` or `from`/`to` in `rules.json`:

| Key | Description |
|---|---|
| `group_id` | QQ group number (string or number) |

```json
{
  "qq_main": { "group_id": "947429526" }
}
```

::: info Group messages only
NextBridge currently bridges **group messages** only. Private messages are not routed.
:::

## Message segments

Incoming messages are parsed from OneBot 11 segment arrays:

| Segment type | Handling |
|---|---|
| `text` | Becomes message text |
| `at` | Converted to `@name` text |
| `image` | Forwarded as `image` attachment |
| `record` | Forwarded as `voice` attachment |
| `video` | Forwarded as `video` attachment |
| `file` | Forwarded as `file` attachment |
| Others (face, reply, forward…) | Silently skipped |

## Sending

| Attachment type | Method |
|---|---|
| `image` | Downloaded and sent as base64 (`base64://…`) |
| `voice` | Downloaded and sent as base64 (`base64://…`) |
| `video` | Downloaded and sent via `file_send_mode` (stream or base64) |
| `file` | Downloaded and sent via `file_send_mode` (stream or base64) |

The `file_send_mode` and `stream_threshold` config keys control how videos and files are uploaded. Stream mode (`upload_file_stream` → `upload_group_file`) is the default and handles large files more reliably. Use `"base64"` if stream upload is unsupported by your NapCat version, and set `stream_threshold` to automatically fall back to stream for files above a given size.

## Notes

- **Self-message echo**: NapCat echoes the bot's own outgoing messages back as events. NextBridge filters these out automatically by comparing `user_id` with `self_id`.
- **Reconnection**: If the WebSocket connection drops, NextBridge automatically reconnects every 5 seconds.
