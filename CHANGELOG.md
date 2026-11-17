# Changelog

All notable changes to NextBridge are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## Unreleased

### Added

- **Runtime rule match conditions.** Rules accept an optional `match` block
  with `keywords` (case-insensitive, any-match) and `users.include` /
  `users.exclude` (platform user id or bound global user id). Conditions are
  evaluated against the source message before forwarding; `connect` rules are
  evaluated per source channel.
- **Hot reload engine.** `command_prefix`, `strict_echo_match`,
  `fuzzy_mention_match`, `mention_notify_control`, `send_timeout`, the rules
  file, sensitive values, and driver instance configs can now be reloaded at
  runtime over the admin API or via `SIGHUP`, without a restart.
- **Driver rebuild from config.** `DriverManager.reload_driver()` stops the old
  instance, clears its bridge registrations, rebuilds it from the (optionally
  new) config, and rolls back to the old instance on failure.
- **Bridge registration helpers.** `unregister_sender` / `unregister_editor` /
  `unregister_deleter` / `unregister_pinner` / `unregister_unpinner` and
  `clear_instance()`.
- **Trackable plugin registrations.** `PluginContext.register_command`,
  `on_event`, `add_receive_middleware`, `add_send_middleware` and `cleanup()`;
  the plugin manager now cleans these up automatically on disable/unload.
- **Plugin restart and dependency checks.** `PluginManager.restart_plugin()`
  and refusal to disable/unload a plugin that other enabled plugins depend on
  (`PluginDependencyError`).
- **Metrics.** In-memory counters (`nextbridge_messages_total`,
  `nextbridge_rule_matches_total`, `nextbridge_send_failures_total`,
  `nextbridge_send_timeouts_total`, `nextbridge_config_reloads_total`,
  `nextbridge_driver_restarts_total`) with a Prometheus endpoint at
  `/_nextbridge/metrics` and periodic snapshots to a new `metrics_counters`
  table so counters survive restarts. Configured via `global.metrics`.
- **Audit logging.** Structured, rotating `logs/audit.log` for admin
  operations (rules/config edits, plugin enable/disable/restart, driver
  restart/reload, auth failures, full reloads), also emitted as `audit.*`
  events on the event bus.
- **Admin HTTP API** under `/_nextbridge`, including rule CRUD, hot-global
  config patching, plugin enable/disable/restart, driver restart/reload, and a
  full reload, with a unified response envelope, optimistic concurrency
  (`If-Match` / `?force=true`), and config redaction.
- **Nickname sanitization.** `global.sanitize_nickname` (default `true`) strips
  non-rendering Unicode characters from sender names before bridging: control
  characters, zero-width/format characters (including `U+200B`-`U+200F` and
  bidi overrides), variation selectors, and line/paragraph separators are
  removed from `nickname`/`username`, formatted bridge headers, and QQ
  forward-node sender names. This prevents names such as `&` + `U+200B` +
  `killjsj` from corrupting bridged output. Hot-reloadable.

### Changed

- **Startup now validates the rules file.** Invalid rules (`RulesFile`/`Rule`
  schema violations) cause startup to be refused instead of being silently
  ignored at runtime.
- **Admin authentication** checks both the username and the password. The
  username is configured with the new `global.plugins.admin.user` (default
  `admin`).
- **Admin endpoints are fail-closed.** When the admin API is disabled,
  `/_nextbridge/plugins`, `/_nextbridge/drivers` and `/_nextbridge/metrics`
  are not reachable (previously `/_nextbridge/plugins` could be reached with an
  empty password). `/_nextbridge/health` remains public.
- **`POST /_nextbridge/admin/reload/{instance_id}`** now rereads the instance
  config and rebuilds the driver. The restart-only behaviour moved to
  `POST /_nextbridge/admin/drivers/{instance_id}/restart`; the old route is
  kept as a deprecated alias.
- **Rule and config writes are atomic** (`temp + fsync + os.replace`) with a
  `.bak` backup and comment/anchor-preserving YAML round-tripping, replacing
  the previous non-atomic `save_config` path used for edits.
- **QQ face GIFs are no longer bundled, and missing ones are fetched.** The
  372-face `db/cqface-gif/` tree left the repo, so checkouts and images are 50 MB
  smaller. `cqface_mode: "gif"` now looks a face up in `<data>/cqface-gif/`
  first, then a leftover `db/cqface-gif/`, and finally downloads it from the
  configured face GIF host instead of dropping the segment. The host is resolved
  with `media.fetch`, so it honours `proxy` and `max_file_size`, and a failure
  still degrades to dropping the segment. `uv run scripts/sync_cqface.py` fills
  the data directory with the full set for offline use.
- **`forward_render_cqface_gif` renamed to `cqface_gif_host`.** The option is no
  longer specific to combined-forward rendering: it now also drives the
  main-message fallback above. The old key still works as a deprecated alias, so
  existing configs keep loading unchanged.
- **QQ face GIF default host moved.** `cqface_gif_host: true` now points at
  `https://cqface.p.wyf9.top/dist/` instead of
  `https://nextbridge.siiway.org/db/cqface-gif/`. Old URLs keep working through
  a 301 redirect on the docs site. Set the option to a custom URL to override.
- **Bare `postgresql://` URLs are pinned to psycopg2.** SQLAlchemy 2.1 changed
  the default DBAPI for the `postgresql://` dialect from psycopg2 to psycopg
  (v3). This project ships `psycopg2-binary` only, so a bare URL now fails with
  `ModuleNotFoundError: psycopg` at startup. NextBridge rewrites
  `postgresql://` to `postgresql+psycopg2://`, leaving URLs that already name a
  driver untouched.
- **Optional driver dependencies load lazily.** Driver modules import their
  third-party libraries inside the code that needs them, so the CLI's driver
  discovery no longer fails when an optional dependency (or a system library it
  needs, such as `libmagic` for WhatsApp) is missing on the host.

### Dependencies

- Added `ruamel.yaml` (comment/anchor-preserving YAML round-trip).
- Added `prometheus-client` (metrics exposition).

### Database

- New migration `5 -> 6` creating the `metrics_counters` table.
