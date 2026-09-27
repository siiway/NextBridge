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

### Dependencies

- Added `ruamel.yaml` (comment/anchor-preserving YAML round-trip).
- Added `prometheus-client` (metrics exposition).

### Database

- New migration `5 -> 6` creating the `metrics_counters` table.
