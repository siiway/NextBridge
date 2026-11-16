---
title: Migrating to v0.4
---

# Migrating to v0.4

::: tip Coming from an older version?
This page covers **v0.3 → v0.4** only. If you are still on v0.3 or earlier, work
through the [v0.3 migration page](https://v0-3-legacy.nextbridge.pages.dev/en/migrate)
first — migration steps are meant to be applied one release at a time.

中文版见 [迁移到 v0.4](/zh/migrate)。
:::

NextBridge does not keep backwards compatibility before 1.0, so a minor version
bump can change config keys and behaviour. This page lists everything that needs
attention when moving from v0.3 to v0.4.

## Before you upgrade

1. **Back up `data/`.** It holds `config.*`, `rules.*`, `data.db` and the
   optional `cqface-map.yaml`.
2. **Check your config keys.** v0.4 validates the config file strictly, so a
   leftover key from an older version now fails at startup instead of being
   ignored. The [Configuration reference](/en/configuration) is the source of
   truth.

## Config changes

### Driver keys

No driver was renamed between v0.3 and v0.4, so a v0.3 config keeps its key
names.

For reference: the QQ driver became `qq` in **v0.3** (it was `napcat` in v0.2
and earlier). If you are upgrading a config that predates v0.3, rename that
block too — NextBridge looks up the driver module by its config key and skips the
instance with a warning when the module is missing.

### New global sections

v0.4 adds several `global.*` blocks. They are all optional with sane defaults,
but the ones below are worth reviewing:

| Key | Why you may want it |
| --- | --- |
| `global.http` | Shared HTTP server for webhook drivers. Yunhu no longer binds its own port (see below). |
| `global.plugins` | Driver/plugin selection, admin API credentials, restart policy. |
| `global.metrics` | Prometheus counters at `/_nextbridge/metrics`. |
| `global.middleware` | Receive/send middleware pipeline. |
| `global.send_timeout` | Offloads slow sends to a background queue. |
| `global.sanitize_nickname` | Strips zero-width and bidi characters from sender names. |

### Per-driver key changes

**Removed / renamed:**

| Driver | v0.3 | v0.4 |
| --- | --- | --- |
| `discord` | `send_as_bot_when_using_cqface_emoji` | `cqface_webhook_fallback` (`"bot"` / `"unicode"`) |
| `yunhu` | `webhook_port` | removed — the webhook is served by the shared `global.http` server; see `webhook_path` |
| `qq` | `forward_render_cqface_gif` | `cqface_gif_host` (old key still accepted as a deprecated alias) |

**Added:**

- `discord`: `enable_recall`, `enable_native_commands`, mention controls
  (`allow_mentions_everyone` / `allow_mentions_users` / `allow_mentions_roles`,
  `sanitize_mass_mentions`), `auto_link_image_hosts`,
  `auto_link_image_show_original_url`
- `telegram`: `enable_recall`, `sanitize_accidental_mentions`,
  `photo_padding_color`
- `qq`: `connection_mode`, `reverse_ws_path`, `edit_via_reply`, `edit_prefix`,
  `enable_recall`, `cqface_gif_host`
- `dingtalk` / `feishu` / `googlechat` / `rocketchat` / `slack` / `teams` /
  `vocechat` / `yunhu`: `webhook_secret`

## Behaviour changes

- **The rules file is validated at startup.** A malformed `rules.*` now refuses
  to start rather than silently ignoring rules at runtime.
- **`cqface_mode: "gif"` can fetch remotely.** Faces missing from the local
  `db/cqface-gif/` database are downloaded from `cqface_gif_host` instead of
  being dropped. GIFs now live at <https://cqface.p.wyf9.top/dist/>; the old
  `nextbridge.siiway.org/db/cqface-gif/` URLs 301 there.
- **Admin API is fail-closed.** With the admin API disabled, only
  `/_nextbridge/health` is public.
- **Slow sends no longer block the queue.** Messages exceeding `send_timeout`
  continue in the background.

## After upgrading

1. Start NextBridge and watch the startup log for config validation errors.
2. The database migrates itself (`5 -> 6` adds the `metrics_counters` table).
3. If you use the admin API, set `global.plugins.admin.user` / `password`.
4. Reload config without a restart with `SIGHUP` or the admin API.
