> This document was written by AI and has been manually reviewed.

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
| `ws_token` | No | — | Access token (appended as `?access_token=...`) |
| `max_file_size` | No | `10485760` (10 MB) | Maximum bytes to download per attachment when sending |
| `cqface_mode` | No | `"gif"` | How to represent QQ face/emoji segments. `"gif"` uploads the face as an animated GIF (from the local `db/cqface-gif/` database); `"emoji"` renders it as inline text, e.g. `:cqface306:`. |
| `file_send_mode` | No | `"stream"` | How to upload files and videos to QQ. `"stream"` uses chunked `upload_file_stream` (recommended for large files); `"base64"` encodes the whole payload and passes it directly to `upload_group_file`. |
| `stream_threshold` | No | `0` (disabled) | If greater than 0, automatically switches to `"stream"` mode when a file or video exceeds this many bytes, regardless of `file_send_mode`. |
| `forward_render_enabled` | No | `false` | Enable merged-forward rendering. When enabled, QQ merged-forward content is rendered to a temporary HTML page and forwarded as a link. |
| `forward_render_ttl_seconds` | No | `86400` | TTL in seconds for merged-forward HTML pages. Pages stay on the same screen and switch to an expired state when the timer runs out. Minimum is 60 seconds. |
| `forward_render_mount_path` | No | `"/napcat-forward"` | Mount path (on the shared HTTP server) used to serve merged-forward pages. |
| `forward_render_persist_enabled` | No | `false` | Enable persistent storage for merged-forward chat records. When enabled, page content is also written to the database so links remain available after restarts. |
| `forward_assets_base_url` | No | `""` | Public base URL used when generating merged-forward links (for example, your reverse-proxy public URL). If empty, NextBridge derives one from `global.http`. |
| `forward_render_cqface_gif` | No | `true` | Rendering strategy for QQ `face` segments inside merged-forward HTML: `false` uses `cqface` unicode mapping; `true`/unset uses built-in default GIF hosts; string uses a custom GIF host base URL. |
| `proxy` | No | — | Proxy URL for WebSocket connection and media downloading (e.g., `http://proxy.example.com:8080` or `socks5://proxy.example.com:1080`). Set to `null` to explicitly disable proxy for this instance (ignores global proxy setting). |

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
| `forward` (merged forward) | Calls `get_forward_msg`, renders a temporary HTML page, and forwards the link; nested forward nodes are rendered recursively; voice nodes are embedded as playable audio, with AMR transcoded to OGG when possible; file nodes show metadata (name/size/file_id) and try to resolve a downloadable URL |
| Others (face...) | Silently skipped; reply segments are shown as a generic reply marker |

::: info Merged-forward access control
Generated merged-forward links include a short token (`t` query parameter), and each page has its own TTL. When the timer runs out, the page stays on screen and switches to an expired state. If persistent storage is enabled, the page can still be opened again after a restart.
:::

::: info Merged-forward face GIF hosts
When `forward_render_cqface_gif=true` (default), NextBridge uses the default GIF host:

- `https://nextbridge.siiway.org/db/cqface-gif/`

If you want to switch to the mainland-accelerated host manually, set `forward_render_cqface_gif` to a string such as:

- `https://nb-res-cn.siiway.top/cqface-gif/`

Both addresses are optional configuration values, and NextBridge does not auto-fallback between them.
:::

## Sending

| Attachment type | Method |
|---|---|
| `image` | Downloaded and sent as base64 (`base64://...`) |
| `voice` | Downloaded and sent as base64 (`base64://...`) |
| `video` | Downloaded and sent via `file_send_mode` (stream or base64) |
| `file` | Downloaded and sent via `file_send_mode` (stream or base64) |

Voice compatibility: when forwarding to other platforms, if a QQ voice attachment is detected as AMR (for example `.amr`), NextBridge first tries to transcode it to `audio/ogg` (Opus) before sending, which improves compatibility on platforms like Discord. If transcoding fails, it automatically falls back to forwarding the original audio.

::: tip ffmpeg requirement
AMR transcoding requires the `ffmpeg` executable to be available on the host system. If ffmpeg is not installed, voice forwarding still works, but AMR→OGG conversion is skipped.
:::

The `file_send_mode` and `stream_threshold` config keys control how videos and files are uploaded. Stream mode (`upload_file_stream` → `upload_group_file`) is the default and handles large files more reliably. Use `"base64"` if stream upload is unsupported by your NapCat version, and set `stream_threshold` to automatically fall back to stream for files above a given size.

## Notes

- **Self-message echo**: NapCat echoes the bot's own outgoing messages back as events. NextBridge filters these out automatically by comparing `user_id` with `self_id`.
- **Reconnection**: If the WebSocket connection drops, NextBridge automatically reconnects every 5 seconds.
