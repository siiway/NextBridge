# QQ

NextBridge connects to QQ via the OneBot 11 WebSocket protocol. Multiple protocol backends are supported: [NapCat](https://napneko.github.io) (default), [Lagrange.OneBot](https://github.com/LagrangeDev/Lagrange.Core), and any generic OneBot 11 implementation.

## Setup

1. Install and run your chosen OneBot 11 backend (e.g. NapCat), configured as a WebSocket server.
2. Note the WebSocket URL (default: `ws://127.0.0.1:3001`) and any access token you configured.
3. Add the instance to `data/config.json`.

## Config keys

Add under `qq.<instance_id>` in `config.json`:

| Key | Required | Default | Description |
|---|---|---|---|
| `protocol` | No | `"napcat"` | OneBot 11 backend protocol: `"napcat"`, `"lagrange"`, or `"onebot_v11"`. Controls which protocol-specific features are available (forward API, stream upload, etc.) |
| `connection_mode` | No | `"forward"` | WebSocket connection direction: `"forward"` has NextBridge connect to NapCat's WebSocket server; `"reverse"` has NapCat connect to a WebSocket server hosted by NextBridge. |
| `ws_url` | No | `ws://127.0.0.1:3001` | NapCat WebSocket server URL when `connection_mode` is `"forward"` |
| `ws_token` | No | — | OneBot access token. Forward mode sends it as the `access_token` query parameter; reverse mode requires NapCat to connect with `Authorization: Bearer <token>`. |
| `reverse_ws_path` | No | `/onebot/v11/<instance_id>` | WebSocket path hosted by NextBridge when `connection_mode` is `"reverse"`. |
| `ws_ssl_verify` | No | `true` | Whether to verify TLS certificates for WSS connections. Set to `false` for self-signed certs |
| `max_file_size` | No | `10485760` (10 MB) | Maximum bytes to download per attachment when sending |
| `cqface_mode` | No | `"gif"` | How to represent QQ face/emoji segments. `"gif"` uploads the face as an animated GIF, reading the local face database first and falling back to the remote host configured by `cqface_gif_host` when a face is missing locally (see [Face GIF assets](#face-gif-assets)). `"emoji"` renders it as inline text, e.g. `:cqface306:`. |
| `file_send_mode` | No | `"stream"` | How to upload files and videos to QQ. `"stream"` uses chunked `upload_file_stream` (recommended for large files); `"base64"` encodes the whole payload and passes it directly to `upload_group_file`. |
| `stream_threshold` | No | `0` (disabled) | If greater than 0, automatically switches to `"stream"` mode when a file or video exceeds this many bytes, regardless of `file_send_mode`. |
| `forward_render_enabled` | No | `false` | Enable QQ combined-forward message rendering as HTML pages |
| `forward_render_ttl_seconds` | No | `15552000` (180 days) | TTL for rendered forward pages in seconds |
| `forward_render_mount_path` | No | `"/qq-forward"` | HTTP mount path for forward page endpoints |
| `forward_render_persist_enabled` | No | `false` | Persist forward pages to database for survival across restarts |
| `forward_render_image_method` | No | `"url"` | Image rendering method for forward pages: `"url"` (serve via DB+bridge URL) or `"base64"` (inline data URI) |
| `forward_render_asset_ttl_seconds` | No | `1209600` (14 days) | TTL for cached forward page images/assets |
| `forward_render_base_url` | No | — | Custom public URL prefix for forward page links. When set, links are generated as `{base_url}/{page_id}` (mount path is NOT appended automatically) |
| `cqface_gif_host` | No | `true` | Face GIF host. Used both for the `<img>` sources in combined-forward HTML pages and as the remote fallback for main-message faces missing from the local face database. `false` disables the remote host entirely (forward rendering falls back to the unicode emoji, and missing faces are dropped), `true` uses the default host `https://cqface.p.wyf9.top/dist/`, and a string sets a custom base URL. |
| `edit_via_reply` | No | `true` | When another platform edits a bridged message, simulate the edit on QQ by sending a new message that quotes the original and prepends `edit_prefix`. Set to `false` to ignore incoming edits entirely. |
| `edit_prefix` | No | `"[编辑]"` | Prefix prepended to the simulated edit message so it is distinguishable from a normal message. Only used when `edit_via_reply` is `true`. |
| `enable_recall` | No | `true` | Whether to sync message recalls. When enabled, recalls on QQ are detected and bridged to other platforms, and recalls from other platforms are applied to QQ via the native `delete_msg` API. Set to `false` to disable recall sync entirely. |
| `proxy` | No | — | Proxy URL for WebSocket connection and media downloading (e.g., `http://proxy.example.com:8080` or `socks5://proxy.example.com:1080`). Set to `null` to explicitly disable proxy for this instance (ignores global proxy setting). |
| `media_proxy` | No | — | Proxy URL used only when fetching media/attachments. Defaults to following `proxy` when unset. |

```json
{
  "qq": {
    "qq_main": {
      "protocol": "napcat",
      "ws_url": "ws://127.0.0.1:3001",
      "ws_token": "your_secret",
      "max_file_size": 10485760
    }
  }
}
```

## Reverse WebSocket connection

Set `connection_mode` to `"reverse"` to make NextBridge host a WebSocket endpoint on the shared HTTP server. In NapCat, create a **WebSocket Client** network configuration pointing to that endpoint. For example, an instance named `qq_main` with NextBridge HTTP listening on port `9080` uses `ws://<NextBridge-host>:9080/onebot/v11/qq_main`. Use `reverse_ws_path` to choose another path.

When `ws_token` is configured, set the same token in NapCat's reverse WebSocket configuration. NextBridge verifies `Authorization: Bearer <token>` so an unauthenticated client cannot control the bot. Each instance accepts only one reverse connection at a time.

## Rule channel keys

Use under `channels` or `from`/`to` in `rules.json`:

| Key | Description |
|---|---|
| `group_id` | QQ group number (string or number) |
| `user_id` | QQ user ID for private/DM messages (string or number) |

```json
{
  "qq_main": { "group_id": "947429526" }
}
```

::: info Group and DM messages
NextBridge bridges **group messages** by default. Private (DM) messages can also be bridged by specifying `user_id` instead of `group_id`. The `/nb bind` commands can be used in DMs.
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
| `face` | Depends on `cqface_mode`: `"gif"` forwards it as a GIF `image` attachment, taken from the local face database or downloaded from the configured face GIF host when missing locally (the segment is dropped only when both fail); `"emoji"` becomes `:cqfaceNNN:` inline text |
| Others (reply, forward...) | Silently skipped |

## Sending

| Attachment type | Method |
|---|---|
| `image` | Downloaded and sent as base64 (`base64://...`) |
| `voice` | Downloaded and sent as base64 (`base64://...`) |
| `video` | Downloaded and sent via `file_send_mode` (stream or base64) |
| `file` | Downloaded and sent via `file_send_mode` (stream or base64) |

The `file_send_mode` and `stream_threshold` config keys control how videos and files are uploaded. Stream mode (`upload_file_stream` → `upload_group_file`) is the default and handles large files more reliably. Use `"base64"` if stream upload is unsupported by your OneBot backend, and set `stream_threshold` to automatically fall back to stream for files above a given size.

## Combined Forward Rendering

When `forward_render_enabled` is `true`, QQ combined-forward messages are rendered as standalone HTML pages with full media support (images, voice, video, files). The rendered pages are accessible via the HTTP server at the configured `forward_render_mount_path`.

- **Page destruction**: Rendered pages are removed when they are destroyed or expire, so refreshes will return 404 instead of reopening the old page.
- **Page settings**: The forward page includes a top-right settings button for color mode and forward display mode, remembered in LocalStorage.
- **Unreliable sender IDs**: When the OneBot backend cannot reliably map a sender ID inside a combined-forward batch, NextBridge labels the UID as unreliable in the rendered page.
- **Per-rule TTL override**: `forward_render_ttl_seconds` can be overridden per-rule via the `msg` config in rules.

## Face GIF assets

Face GIFs are **not bundled** with NextBridge. With `cqface_mode: "gif"`, a face is looked up in the local database first and only downloaded when it is missing:

1. `<data>/cqface-gif/<id>.gif` (a synced copy; this is what you normally use)
2. `db/cqface-gif/<id>.gif` in a source checkout, if you still have one
3. `<cqface_gif_host><id>.gif`, the remote host

To keep a full local copy (offline use or a self-hosted deploy), sync it into the data directory:

```sh
uv run scripts/sync_cqface.py
# or point it at another data directory / mirror
uv run scripts/sync_cqface.py --dest /srv/nextbridge/data/cqface-gif
```

The script downloads the [wyf9/cqface](https://github.com/wyf9/cqface) archive and writes `dist/*.gif` into the target directory, skipping files that already exist unless `--force` is given. Faces added locally by hand are therefore never overwritten by accident.

## Message Edit Sync

QQ (OneBot 11) has **no native "edit message" API**, so an edit made on another platform (Discord/Telegram) cannot be applied to the original QQ message in place. Instead, NextBridge **simulates** the edit:

- When an edit is bridged to QQ, NextBridge sends a **new message** that **quotes (replies to)** the original bridged message and prepends `edit_prefix` (default `[编辑]`).
- Repeated edits always quote the **original** bridged message, so the edit thread stays anchored to it.
- Each simulated edit message is saved in the message mapping, allowing later edits, recalls, or replies to that `[编辑]` message to continue through bridge routing.
- Only text content is synced. Attachments are not re-sent on edit.
- Set `edit_via_reply` to `false` to disable this behavior and ignore incoming edits.

## Message Recall Sync

QQ (OneBot 11) has **native message recall support**, so recalls can be synced in both directions:

- **Detection**: When a message is recalled on QQ, the OneBot backend pushes a `group_recall` (group) or `friend_recall` (private) notice event, which NextBridge uses to bridge the recall to other platforms.
- **Application**: Recalls made on other platforms (Discord/Telegram) are applied to the corresponding bridged message on QQ via the native `delete_msg` API.
- If a source message was split into multiple QQ messages, all corresponding messages are deleted on recall.
- Set `enable_recall` to `false` to disable both detection and application of recalls.

## Notes

- **Self-message echo**: The OneBot backend echoes the bot's own outgoing messages back as events. NextBridge filters these out automatically by comparing `user_id` with `self_id`.
- **Reconnection**: If the WebSocket connection drops, NextBridge automatically reconnects every 5 seconds.
