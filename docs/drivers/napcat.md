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
| `forward_render_ttl_seconds` | No | `15552000` (180 days) | TTL in seconds for merged-forward HTML pages. Pages stay on the same screen and switch to an expired state when the timer runs out. Minimum is 60 seconds. |
| `forward_render_mount_path` | No | `"/napcat-forward"` | Mount path (on the shared HTTP server) used to serve merged-forward pages. |
| `forward_render_persist_enabled` | No | `false` | Enable persistent storage for merged-forward chat records. When enabled, page content is also written to the database so links remain available after restarts. |
| `forward_render_image_method` | No | `"url"` | Image rendering method for merged-forward HTML. `"url"` stores image bytes in DB and serves via bridge asset URLs; `"base64"` embeds image data URIs directly into the page. |
| `forward_render_base_url` | No | `""` | Preferred public URL prefix for merged-forward links. When set, links are generated as `${forward_render_base_url}/{page_id}` and do **not** auto-append `forward_render_mount_path`. Useful for path-based reverse proxy setups. |
| `forward_render_asset_ttl_seconds` | No | `1209600` (14 days) | TTL in seconds for merged-forward image assets served from the bridge's own HTTP endpoint. Set to `0` for infinite validity. |
| `forward_render_cqface_gif` | No | `true` | Rendering strategy for QQ `face` segments inside merged-forward HTML: `false` uses `cqface` unicode mapping; `true`/unset uses built-in default GIF hosts; string uses a custom GIF host base URL. |
| `proxy` | No | — | Proxy URL for WebSocket connection and media downloading (e.g., `http://proxy.example.com:8080` or `socks5://proxy.example.com:1080`). Set to `null` to explicitly disable proxy for this instance (ignores global proxy setting). |

Forward link base URL priority:
1. `forward_render_base_url` (no mount path auto-append)
2. `global.base_url` (auto-appends mount path)
3. derived from `global.http` host/port

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
| `image` | Forwarded as `image` attachment; in merged-forward: image rendering follows `forward_render_image_method` (`url` or `base64`) |
| `record` | Forwarded as `voice` attachment; in merged-forward: embedded as playable audio, with AMR transcoded to OGG when possible |
| `video` | Forwarded as `video` attachment; in merged-forward: embedded with `<video controls>` |
| `file` | Forwarded as `file` attachment; in merged-forward: shows metadata (name/size/file_id) and attempts to resolve a downloadable URL |
| `forward` (merged forward) | Calls `get_forward_msg`, renders a temporary HTML page, and forwards the link; nested forward nodes are rendered recursively; voice nodes are embedded as playable audio; image/mface rendering follows `forward_render_image_method`; file nodes show metadata |
| Others (face...) | Silently skipped; reply segments are shown as a generic reply marker |

For merged-forward images, clicking the image now opens the bridge-rendered resource (`/asset/...`) in `url` mode, instead of jumping to the original QQ CDN URL. In `base64` mode, the page opens the image via a temporary blob URL without adding a duplicate base64 `href` payload.

For security hardening, merged-forward image embedding now only allows a safe MIME allowlist (JPEG/PNG/GIF/WebP/BMP/AVIF). Unsafe types (for example `text/html` or `image/svg+xml`) are blocked from inline rendering and shown as a placeholder link.

When merged-forward sender UID reliability cannot be confidently verified (including single-sender batches), NextBridge marks that sender as `UID 不可信` in the rendered header.

Even when UID is marked unreliable, the rendered header still displays the QQ number (with the `UID 不可信` tag) for manual verification.

::: info Merged-forward access control
Merged-forward links are plain paths and each page has its own TTL. When the timer runs out, the page stays on screen and switches to an expired state. If persistent storage is enabled, the page can still be opened again after a restart.
:::

::: info Rule-level forward TTL override
You can override merged-forward page TTL per rule with `msg.forward_render_ttl_seconds` (minimum 60). In `connect` rules, channel-level `channels.<instance>.msg.forward_render_ttl_seconds` takes precedence over rule-level `msg.forward_render_ttl_seconds`.
:::

::: info Merged-forward face GIF hosts
When `forward_render_cqface_gif=true` (default), NextBridge uses the default GIF host:

- `https://nextbridge.siiway.org/db/cqface-gif/`

If you want to switch to the China Mainland-accelerated host manually, set `forward_render_cqface_gif` to a string such as:

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
