---
title: Migrating to v0.3
---

# Migrating to v0.3

::: tip This is a frozen page
You are reading the **v0.3** docs. The latest release is
[v0.4](https://nextbridge.siiway.org/en/migrate).
:::

This page covers **v0.2.1 → v0.3**. If you are on an even older build, upgrade to
v0.2.1 first.

## Before you upgrade

1. **Back up `data/`** (`config.*`, `rules.*`, `data.db`).
2. **Read your config through.** v0.3 validates driver configs strictly, so keys
   that were silently ignored before now fail at startup.

## Config changes

### QQ config key renamed

The QQ driver moved from `napcat` to `qq`, because it now speaks three backends
rather than just NapCat:

```diff
-  "napcat": {
+  "qq": {
     "qq_main": {
+      "protocol": "napcat",
       "ws_url": "ws://127.0.0.1:3001"
     }
   }
```

`protocol` accepts `"napcat"` (default), `"lagrange"`, or `"onebot_v11"`.

### New `global` keys

| Key | Notes |
| --- | --- |
| `global.command_prefix` | Prefix for built-in commands, default `nb` (written without the slash). |
| `global.base_url` | Public URL used when generating externally reachable links. |
| `global.http` | Shared HTTP server (`host` / `port` / `root_path` / `log_level` / `enable`) for webhook drivers. |

### Per-driver key changes

**Removed / renamed:**

| Driver | v0.2.1 | v0.3 |
| --- | --- | --- |
| `discord` | `send_as_bot_when_using_cqface_emoji` | `cqface_webhook_fallback` (`"bot"` / `"unicode"`) |
| `yunhu` | `webhook_port` | removed — the webhook is served by the shared `global.http` server |
| `feishu` | `listen_port` | removed — same, served by `global.http` |

**Added:**

- `qq`: `protocol`, `ws_ssl_verify`, and the whole `forward_render_*` family
  (`forward_render_enabled`, `_ttl_seconds`, `_mount_path`,
  `_persist_enabled`, `_image_method`, `_asset_ttl_seconds`, `_base_url`,
  `_cqface_gif`)
- `discord`: `allow_mentions_everyone`, `allow_mentions_users`,
  `allow_mentions_roles`, `sanitize_mass_mentions`
- `telegram`: `photo_padding_color`

## Behaviour changes

- **Combined-forward rendering** can now be emitted as HTML pages instead of a
  text summary. Enable it with `forward_render_enabled` and point
  `forward_render_base_url` at your public address.
- **QQ faces** can be bridged as GIF attachments (`cqface_mode: "gif"`) or as
  inline `:cqfaceNNN:` tokens expanded per-platform (`"emoji"`).
- **Webhook drivers share one HTTP server**, so Yunhu and Feishu no longer each
  need their own `*_port` setting.

## After upgrading

1. Start NextBridge and check the startup log for config validation errors.
2. If you use webhook drivers, make sure `global.http.enable` is `"true"` (or
   that at least one webhook driver instance mounts a route).
