> This document was written by AI and has been manually reviewed.

# Plugin Development

NextBridge supports a general plugin system for extending functionality beyond driver integrations. Plugins can subscribe to events, register custom commands, add database migrations, and access the full bridge API.

## Plugin Architecture

A plugin is a Python class inheriting from `BasePlugin` with a `PluginMeta` descriptor. It registers itself at import time via `plugins.registry.register()`.

### Plugin Lifecycle

| Phase | Method | Description |
|---|---|---|
| Registration | `register("name", PluginClass)` | Called at module import time |
| Load | `async on_load(ctx)` | Receive `PluginContext`, do initial setup |
| Enable | `async on_enable()` | Subscribe to events, register commands |
| Disable | `async on_disable()` | Extra cleanup only — tracked registrations are removed automatically |
| Unload | `async on_unload()` | Final cleanup before removal |
| Restart | `PluginManager.restart_plugin(name)` | `disable → unload → load → enable` in one step |

### Plugin States

`CREATED` → `LOADED` → `ENABLED` → `DISABLED` → `UNLOADED`

## Creating a Plugin

### Step 1: Define the plugin class

```python
from plugins import BasePlugin, PluginMeta
from plugins.registry import register


class MyPlugin(BasePlugin):
    meta = PluginMeta(
        name="my_plugin",
        version="1.0.0",
        display_name="My Plugin",
        description="Does something useful",
        author="You",
        dependencies=[],
    )

    async def on_load(self, ctx):
        self._ctx = ctx

    async def on_enable(self):
        pass

    async def on_disable(self):
        pass

    async def on_unload(self):
        pass


register("my_plugin", MyPlugin)
```

### Step 2: Configure it

```yaml
global:
  plugins:
    general:
      enabled:
        - my_plugin
    config:
      my_plugin:
        key: value
```

## PluginContext

The `PluginContext` object provides access to core services:

| Property | Type | Description |
|---|---|---|
| `ctx.bridge` | `Bridge` | Core routing engine — register commands, inspect senders |
| `ctx.event_bus` | `EventBus` | Subscribe to lifecycle and message events |
| `ctx.middleware` | `MiddlewareChain` | Register receive/send middlewares |
| `ctx.http_server` | `HttpServerManager` | Mount HTTP sub-apps (if HTTP server is running) |
| `ctx.config` | `dict` | Plugin-specific configuration from `plugins.config.<name>` |
| `ctx.version` | `str` | NextBridge version string |
| `ctx.config_path` | `Path` | Path to the config file |
| `ctx.data_path` | `str` | Runtime data directory |
| `ctx.db()` | `MessageDB` | Database access for message/user mappings |
| `ctx.media()` | `module` | Media utilities (download attachments, convert formats) |
| `ctx.logger(name)` | `Logger` | Get a loguru logger |

### Trackable registration helpers

Prefer the following helpers over calling `ctx.bridge` / `ctx.event_bus` / `ctx.middleware` directly. The plugin manager records every registration made through them and removes it automatically when the plugin is disabled or unloaded, so no manual teardown is required.

| Helper | Description |
|---|---|
| `ctx.register_command(name, handler)` | Register a `/<prefix> <name>` command |
| `ctx.on_event(event, handler)` | Subscribe to an `EventBus` event |
| `ctx.add_receive_middleware(name, handler, priority=100)` | Add a receive middleware |
| `ctx.add_send_middleware(name, handler, priority=100)` | Add a send middleware |
| `ctx.cleanup()` | Manually remove all tracked registrations |

## Registering Commands

Plugins can register custom commands that users invoke via `/<prefix> <command>`:

```python
class MyPlugin(BasePlugin):
    async def on_enable(self):
        self._ctx.register_command("hello", self._handle_hello)

    async def _handle_hello(self, msg, args):
        sender_info = self._ctx.bridge._senders.get(msg.instance_id)
        if sender_info:
            _, sender = sender_info
            await sender(msg.channel, "Hello from MyPlugin!")
```

The handler receives `(msg: NormalizedMessage, args: list[str])`.

## Subscribing to Events

Use `ctx.on_event` to react to system events; the subscription is removed automatically on disable/unload:

```python
class MyPlugin(BasePlugin):
    async def on_enable(self):
        self._ctx.on_event("bridge.message", self._on_message)

    async def _on_message(self, instance_id, platform, channel, text, **kwargs):
        # called for every bridged message
        pass
```

### Standard Events

| Event | Args |
|---|---|
| `bridge.message` | `instance_id`, `platform`, `channel`, `user`, `user_id`, `text`, `message_id`, `time`, `attachments` |
| `driver.starting` | `instance_id` |
| `driver.started` | `instance_id` |
| `driver.crashed` | `instance_id`, `error` |
| `driver.stopped` | `instance_id` |
| `health_changed` | `driver`, `old`, `new` |
| `plugin.loaded` | `name` |
| `plugin.enabled` | `name` |
| `plugin.disabled` | `name` |
| `plugin.error` | `name`, `error` |

## Dependencies

A plugin can declare other plugins it depends on via `PluginMeta.dependencies`. While a dependency is loaded or enabled, disabling/unloading it is refused (raises `PluginDependencyError`); unload the dependents first. Startup shutdown ignores this and force-unloads everything.

## Custom DB Migrations

Plugins can register their own database migration steps:

```python
from pathlib import Path
from services.db_migrations import register_plugin_migration

MIGRATION_FILE = Path(__file__).parent / "migrations" / "0-1.py"
register_plugin_migration(from_version=0, to_version=1, file_path=MIGRATION_FILE)
```

The migration file must export an `upgrade(conn, dialect_name)` function matching the same contract as built-in migrations.

## Plugin Discovery

Plugins are discovered from four sources (in priority order, later overrides earlier):

| Source | Location |
|---|---|
| Built-in | `plugins/*.py` in the project directory |
| Entry points | Pip packages advertising `nextbridge.plugins` entry point group |
| External | Pip packages declared in `plugins.general.external` |
| Local paths | Directories listed in `plugins.paths` |

## Configuration Reference

| Key | Type | Default | Description |
|---|---|---|---|
| `plugins.general.enabled` | `list[str]` | `[]` | Plugin names to enable |
| `plugins.general.external` | `dict` | `{}` | External plugin modules, keyed by name |
| `plugins.paths` | `list[str]` | `[]` | Local directories to scan for plugin `.py` files |
| `plugins.config` | `dict[str, dict]` | `{}` | Per-plugin configuration, keyed by plugin name |

### External plugin config

```yaml
plugins:
  general:
    external:
      my_plugin:
        module: "nextbridge_myplugin"
```

## Driver Plugins

Drivers are distributed separately from general plugins. A pip-installed
driver is auto-discovered if it advertises the `nextbridge.drivers` entry
point group:

```toml
[project.entry-points."nextbridge.drivers"]
myplatform = "nextbridge_myplatform.driver"
```

The module must call `drivers.registry.register()` (and optionally
`drivers.registry.register_cli()`) at import time. Alternatively, declare it
in `global.plugins.drivers.external`, or drop a `.py` file into a directory
listed in `global.plugins.paths` — see
[Configuration → External drivers](./configuration#external-drivers) for the
full priority table and examples.

## Built-in Plugins

### stats

Counts bridged messages across platforms and reports via `/<prefix> stats` command.

**Configuration:**

```yaml
plugins:
  config:
    stats:
      interval: 300
```

## Admin API

Plugins can be inspected and controlled via the admin API (all responses use the unified `{"ok": ..., "data": ...}` envelope):

```
GET  /_nextbridge/plugins
POST /_nextbridge/admin/plugins/{name}/enable
POST /_nextbridge/admin/plugins/{name}/disable
POST /_nextbridge/admin/plugins/{name}/restart
```

`GET` returns:

```json
{
  "ok": true,
  "data": {
    "plugins": {
      "stats": {
        "state": "ENABLED",
        "version": "1.0.0",
        "error": null,
        "source": "builtin"
      }
    }
  }
}
```

Requires HTTP Basic Auth (`plugins.admin.user` / `plugins.admin.password`). See the [Admin API](./admin-api) page for the full reference.