> This document was written by AI and has been manually reviewed.

# Admin API

NextBridge exposes a small HTTP API for runtime inspection and management. It is served by the shared HTTP server under the `/_nextbridge` prefix.

::: warning Disabled by default
The API is only reachable when `global.plugins.admin.enable` is `true` and a password is set. Otherwise every route except `GET /_nextbridge/health` returns `404`.
:::

## Authentication

All routes except `GET /_nextbridge/health` require HTTP Basic Auth using the credentials from:

```yaml
global:
  plugins:
    admin:
      enable: true
      user: admin
      password: change-me
```

Authentication is fail-closed: if the admin API is disabled, protected routes do not exist at all. Failed attempts are recorded in the audit log.

## Response format

Every response except `GET /_nextbridge/metrics` is wrapped in a consistent envelope; the metrics endpoint returns Prometheus text format.

Success:

```json
{ "ok": true, "data": { } }
```

Error:

```json
{
  "ok": false,
  "error": {
    "code": "invalid_rules",
    "message": "human readable message",
    "details": null
  }
}
```

Common status codes: `400` validation error, `401` authentication failure, `404` unknown target, `409` optimistic-lock conflict, `503` reload engine unavailable.

## Read endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/_nextbridge/health` | Liveness probe. Public, no auth. |
| `GET` | `/_nextbridge/drivers` | Driver instance status |
| `GET` | `/_nextbridge/plugins` | Plugin status |
| `GET` | `/_nextbridge/metrics` | Prometheus text exposition |
| `GET` | `/_nextbridge/rules` | Current rules plus file path and content hash |
| `GET` | `/_nextbridge/config` | Current config, with sensitive values redacted |

## Rules

Rules are stored in the rules file (`rules.yaml` / `rules.json` / `rules.toml`), which remains the source of truth. Every write is validated, backed up (`.bak`), written atomically, then hot-reloaded.

| Method | Path | Description |
|---|---|---|
| `POST` | `/_nextbridge/admin/rules` | Append a single rule (body is one rule object) |
| `PUT` | `/_nextbridge/admin/rules` | Replace the whole rules list (body `{"rules": [...]}`) |
| `PATCH` | `/_nextbridge/admin/rules/{id}` | Merge the body into the rule with this id |
| `DELETE` | `/_nextbridge/admin/rules/{id}` | Delete the rule with this id |

### Optimistic concurrency

To avoid clobbering an edit made outside the API, send the `sha256` you last read (from `GET /_nextbridge/rules`) as the `If-Match` header. If the file changed, the request fails with `409 conflict`. Pass `?force=true` to overwrite anyway.

## Configuration

| Method | Path | Description |
|---|---|---|
| `PATCH` | `/_nextbridge/admin/config` | Update hot-reloadable global keys |

Only these keys may be changed at runtime (body `{"keys": {"command_prefix": "nb"}}`); anything else returns `400 not_hot_reloadable` with the allowed set in `details`:

`command_prefix`, `strict_echo_match`, `fuzzy_mention_match`, `mention_notify_control`, `send_timeout`, `sanitize_nickname`.

## Plugins

| Method | Path | Description |
|---|---|---|
| `POST` | `/_nextbridge/admin/plugins/{name}/enable` | Enable a plugin |
| `POST` | `/_nextbridge/admin/plugins/{name}/disable` | Disable a plugin |
| `POST` | `/_nextbridge/admin/plugins/{name}/restart` | `disable → unload → load → enable` |

Disabling a plugin whose dependents are still active fails with `409`.

## Drivers

| Method | Path | Description |
|---|---|---|
| `POST` | `/_nextbridge/admin/drivers/{instance_id}/restart` | Restart the driver with its current config |
| `POST` | `/_nextbridge/admin/drivers/{instance_id}/reload` | Re-read config and rebuild the driver instance |
| `POST` | `/_nextbridge/admin/reload/{instance_id}` | **Deprecated** alias for `restart` |

Reloading rebuilds the instance from the on-disk config. The HTTP mount path of a driver's webhook cannot be changed at runtime.

## Full reload

| Method | Path | Description |
|---|---|---|
| `POST` | `/_nextbridge/admin/reload` | Reload config, rules, and every changed driver |

## SIGHUP

Sending `SIGHUP` to the process performs the same full reload as `POST /_nextbridge/admin/reload`.

## Audit log

Every write operation and authentication failure is appended to `logs/audit.log` (rotated using the `global.log.*` rotation settings) as one JSON object per line, and emitted on the event bus as `audit.<event>`. Fields:

`ts`, `event`, `actor`, `source_ip`, `target`, `before`, `after`, `result`, `error`.

Only the last 500 characters of `before` / `after` are kept.
