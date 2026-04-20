> This document was written by AI and has been manually reviewed.

# QQ Driver

NextBridge connects to QQ through a single driver with three protocol modes:

- `napcat` - full-featured WebSocket mode, including `upload_file_stream`
- `lagrange` - OneBot 11 over WebSocket, using protocol-compatible APIs and path-based group-file upload
- `onebot_v11` - generic OneBot 11 mode for implementations that expose the standard API surface

## Protocol references

Use these links to choose and deploy your QQ bot server implementation (non-LLMS docs):

| Mode         | Website / docs                             | Repository                                     |
| ------------ | ------------------------------------------ | ---------------------------------------------- |
| `napcat`     | https://napneko.github.io                  | https://github.com/NapNeko/NapCatQQ            |
| `lagrange`   | https://lagrangedev.github.io/Lagrange.Doc | https://github.com/LagrangeDev/Lagrange.OneBot |
| `onebot_v11` | https://11.onebot.dev                      | https://github.com/botuniverse/onebot-11       |

## Setup

1. Install and run your selected QQ bot server (NapCat, Lagrange, or another OneBot 11 implementation) in WebSocket server mode.
2. Note the WebSocket URL (commonly `ws://127.0.0.1:3001`) and access token if configured.
3. Add the instance under `qq.<instance_id>` in `config.json` and set `protocol`.

## Configuration

Add under `qq.<instance_id>` in `config.json`:

| Key                                | Required | Default               | Description                                                                                                                                                                                      |
| ---------------------------------- | -------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `protocol`                         | No       | `napcat`              | Protocol mode: `napcat`, `lagrange`, or `onebot_v11`                                                                                                                                             |
| `ws_url`                           | No       | `ws://127.0.0.1:3001` | WebSocket URL of the QQ bot server                                                                                                                                                               |
| `ws_token`                         | No       | —                     | Access token (appended as `?access_token=...`)                                                                                                                                                   |
| `ws_ssl_verify`                    | No       | `true`                | Whether to verify TLS certificates for `wss://` WebSocket URLs. Set to `false` only when your bot server uses a self-signed/private CA certificate.                                              |
| `max_file_size`                    | No       | `10485760` (10 MB)    | Maximum bytes to download per attachment when sending                                                                                                                                            |
| `cqface_mode`                      | No       | `"gif"`               | How to represent QQ face segments. `"gif"` uploads faces from the local `db/cqface-gif/` database; `"emoji"` renders inline text like `:cqface306:`.                                             |
| `file_send_mode`                   | No       | `"stream"`            | Upload mode used by NapCat. `"stream"` uses `upload_file_stream`; `"base64"` sends `base64://...` payloads directly. Lagrange and generic OneBot modes fall back to path-based upload for files. |
| `stream_threshold`                 | No       | `0` (disabled)        | If greater than 0, switches to `stream` mode for large files when using NapCat, regardless of `file_send_mode`.                                                                                  |
| `forward_render_enabled`           | No       | `false`               | Enable merged-forward rendering to HTML pages. Supported in `napcat` and `lagrange` modes.                                                                                                       |
| `forward_render_ttl_seconds`       | No       | `15552000` (180 days) | TTL for merged-forward HTML pages. Minimum is 60 seconds.                                                                                                                                        |
| `forward_render_mount_path`        | No       | `"/qq-forward"`       | Mount path for merged-forward pages on the shared HTTP server. The default becomes `"/qq-forward/<instance_id>"` automatically.                                                                  |
| `forward_render_persist_enabled`   | No       | `false`               | Persist merged-forward pages to the database so links survive restarts.                                                                                                                          |
| `forward_render_image_method`      | No       | `"url"`               | How images are rendered in merged-forward HTML. `"url"` stores bytes in DB; `"base64"` embeds data URIs.                                                                                         |
| `forward_render_base_url`          | No       | `""`                  | Public URL prefix for forward links. If set, links are generated as `${forward_render_base_url}/{page_id}`.                                                                                      |
| `forward_render_asset_ttl_seconds` | No       | `1209600` (14 days)   | TTL for merged-forward image assets served by the bridge. Set to `0` for infinite validity.                                                                                                      |
| `forward_render_cqface_gif`        | No       | `true`                | Rendering strategy for `face` segments inside merged-forward HTML.                                                                                                                               |
| `proxy`                            | No       | —                     | Proxy URL for WebSocket connection and media downloading. Set to `null` to disable proxy for this instance.                                                                                      |

Forward link base URL priority:
1. `forward_render_base_url` (no mount-path auto-append)
2. `global.base_url` (auto-appends mount path)
3. derived from `global.http` host/port

```json
{
  "qq": {
    "qq_main": {
      "protocol": "lagrange",
      "ws_url": "ws://127.0.0.1:3001",
      "ws_token": "your_secret"
    }
  }
}
```

## Routing

Use under `channels` or `from`/`to` in `rules.json`:

| Key        | Description                        |
| ---------- | ---------------------------------- |
| `group_id` | QQ group number (string or number) |

```json
{
  "qq_main": { "group_id": "947429526" }
}
```

::: info Group messages only
NextBridge currently bridges **group messages** only. Private messages are not routed.
:::

## Behavior by protocol

| Feature                  | napcat | lagrange | onebot_v11  |
| ------------------------ | ------ | -------- | ----------- |
| Message receive/send     | Yes    | Yes      | Yes         |
| Merged-forward rendering | Yes    | Yes      | No          |
| `upload_file_stream`     | Yes    | No       | No          |
| Group file upload        | Yes    | Yes      | Best effort |
| Group file URL lookup    | Yes    | Yes      | Best effort |

## Message segments

Incoming messages are parsed from OneBot 11 segment arrays:

| Segment type                            | Handling                                                                                                                                                                                                                            |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `text`                                  | Becomes message text                                                                                                                                                                                                                |
| `at`                                    | Converted to `@name` text                                                                                                                                                                                                           |
| `image`                                 | Forwarded as `image` attachment; in merged-forward: image rendering follows `forward_render_image_method` (`url` or `base64`)                                                                                                       |
| `record`                                | Forwarded as `voice` attachment; in merged-forward: embedded as playable audio, with AMR transcoded to OGG when possible                                                                                                            |
| `video`                                 | Forwarded as `video` attachment; in merged-forward: embedded with `<video controls>`                                                                                                                                                |
| `file`                                  | Forwarded as `file` attachment; for `napcat` mode, streamed via `upload_file_stream`, otherwise uploaded through a local temporary path and then sent with `upload_group_file` (best when the bot can see the same filesystem path) |
| `forward`                               | Calls `get_forward_msg`, renders a temporary HTML page, and forwards the link; nested forward nodes are rendered recursively                                                                                                        |
| `face`                                  | Rendered from the local cqface GIF database or inline text, depending on `cqface_mode`                                                                                                                                              |
| Others (`reply`, `json`, `mface`, etc.) | Parsed when possible; unsupported types are skipped or shown as text fallback                                                                                                                                                       |

Merged-forward image behavior:
- In `url` mode, image clicks open bridge-served assets (`/asset/...`) instead of original QQ CDN links.
- In `base64` mode, images are embedded directly and opened via browser blob/data behavior.

Security hardening in merged-forward rendering:
- Inline image MIME is restricted to a safe allowlist (`JPEG/PNG/GIF/WebP/BMP/AVIF`).
- Unsafe MIME types (for example `text/html` or `image/svg+xml`) are blocked from inline rendering and shown as placeholder links.

Forward sender UID reliability:
- If sender UID reliability cannot be verified (including some single-sender batches), the page marks that sender as `UID 不可信`.
- Even when marked unreliable, the QQ number is still shown for manual verification.

::: info Merged-forward access control
Merged-forward links are plain paths and each page has its own TTL. When TTL expires, the current page transitions to an expired state in place. If persistent storage is enabled, pages can still be reopened after restart.
:::

::: info Rule-level forward TTL override
You can override merged-forward page TTL per rule with `msg.forward_render_ttl_seconds` (minimum 60). In `connect` rules, channel-level `channels.<instance>.msg.forward_render_ttl_seconds` takes precedence over rule-level `msg.forward_render_ttl_seconds`.
:::

::: info Merged-forward face GIF hosts
When `forward_render_cqface_gif=true` (default), NextBridge uses:

- `https://nextbridge.siiway.org/db/cqface-gif/`

You can switch to another host by setting `forward_render_cqface_gif` to a string, for example:

- `https://nb-res-cn.siiway.top/cqface-gif/`

NextBridge does not auto-fallback between host URLs.
:::

## Sending

| Attachment type | Method                                                                                                                    |
| --------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `image`         | Downloaded and sent as base64 (`base64://...`)                                                                            |
| `voice`         | Downloaded and sent as base64 (`base64://...`)                                                                            |
| `video`         | In `napcat` mode: sent by `file_send_mode` (`stream`/`base64`); in `lagrange`/`onebot_v11`: best-effort path-based upload |
| `file`          | In `napcat` mode: sent by `file_send_mode` (`stream`/`base64`); in `lagrange`/`onebot_v11`: best-effort path-based upload |

Voice compatibility: when forwarding to other platforms, if QQ voice is detected as AMR (for example `.amr`), NextBridge first attempts transcoding to `audio/ogg` (Opus), which improves compatibility on platforms like Discord. If transcoding fails, it falls back to the original audio.

::: tip ffmpeg requirement
AMR transcoding requires `ffmpeg` to be available on the host. Without ffmpeg, voice forwarding still works, but AMR -> OGG conversion is skipped.
:::

`file_send_mode` and `stream_threshold` mainly affect `napcat` mode. Stream mode (`upload_file_stream` -> `upload_group_file`) is the default and is generally more reliable for large files. Use `base64` if your implementation does not support stream upload.

## Notes

- Self-message echo: some QQ bot servers echo the bot's own outgoing messages as inbound events. NextBridge filters these by comparing `user_id` and `self_id`.
- Reconnection: if the WebSocket connection drops, NextBridge reconnects automatically every 5 seconds.
- TLS certificates: if `wss://` connection fails with `CERTIFICATE_VERIFY_FAILED` and your deployment uses self-signed/internal CA certs, set `ws_ssl_verify` to `false` for that QQ instance.
