> This document was written by AI and has been manually reviewed.

# User Commands

NextBridge supports several built-in commands that users can type directly into their chat platforms to manage their identity and cross-platform experience.

> **Note:** Built-in commands live under the `nb` namespace, e.g. `/nb bind` and `/nb bind confirm`. The `nb` prefix is configurable via the global `command_prefix` option — if changed, replace `nb` accordingly.

## `/nb bind`

Manage cross-platform account bindings for @mention routing.

By default, NextBridge tries to map mentions across platforms by matching **display names**. Account binding lets you explicitly link your IDs across platforms so mentions always target the correct account.

| Command | Description |
|---|---|
| `/nb bind setup` | Generate a 6-digit binding code (valid for 5 minutes) |
| `/nb bind confirm <code>` | Confirm a binding code from another platform |
| `/nb bind rm [instance_id]` | Remove a specific binding or all bindings |
| `/nb bind list` | List all linked accounts |

### Example

1. On **Platform A** (e.g. Discord), type `/nb bind setup` — NextBridge replies with a 6-digit code (e.g. `123456`).
2. On **Platform B** (e.g. QQ), type `/nb bind confirm 123456`.
3. Your accounts are now linked: mentions of you on either platform resolve to your bound accounts elsewhere.

## `/nb notify`

Control which bound platforms receive @mention notifications.

> **Config toggle**: `global.mention_notify_control` (default `true`). Set to `false` to disable this feature globally.

| Command | Description |
|---|---|
| `/nb notify mode all` | Receive @mention notifications on all bound platforms (default) |
| `/nb notify mode whitelist` | Only receive notifications on explicitly added platforms |
| `/nb notify mode blacklist` | Receive notifications on all platforms except listed ones |
| `/nb notify add <instance_id>` | Add a platform to the whitelist/blacklist (e.g. `qq`, `discord`, `telegram`) |
| `/nb notify rm <instance_id>` | Remove a platform from the list |
| `/nb notify list` | Show current notification preference |

### Modes

- **all** — Default. All bound platforms receive @mention notifications.
- **whitelist** — Only platforms added via `notify add` receive notifications.
- **blacklist** — All platforms except those added via `notify add` receive notifications.

### Example

```
/nb notify mode whitelist
/nb notify add discord
/nb notify add qq
/nb notify list
```

After this setup, @mention notifications are only delivered to Discord and QQ bound accounts, even if Telegram is also bound.

## `/nb status`

View NextBridge's runtime status and version info.

```
/nb status
```

The reply includes the version (stable releases show the version number, development builds show the commit hash), uptime, per-platform driver status, and rule count.

## `/nb help`

Show the built-in command help.

```
/nb help
```

## `/ping`

Look up a user by nickname across platforms and tag them.

```
/ping <nickname>
```

## Discord native commands

When the Discord driver runs with a bot token (and `enable_native_commands` is not disabled), NextBridge registers native slash commands. They mirror the text commands above but expose the structural tokens as subcommands and choice menus, so you never type them by hand:

```
/nb bind setup
/nb bind confirm code:<code>
/nb bind rm [instance_id:<instance_id>]
/nb bind list
/nb notify mode mode:<all|whitelist|blacklist>
/nb notify add instance_id:<instance_id>
/nb notify rm instance_id:<instance_id>
/nb notify list
/nb status
/nb help
/ping
```

- Actions (`setup`, `confirm`, `mode`, ...) are offered as subcommands; `mode` is a choice menu. Only free-form values such as the binding `<code>` and `<instance_id>` are typed as text.
- The root command name follows `command_prefix`. If the prefix is not a valid Discord command name (1–32 chars of lowercase letters, digits, `-` or `_`), the driver falls back to `nb` and logs a warning.
- Changing `command_prefix` requires a restart to update the registered slash-command names.

## Configuration

### `mention_notify_control`

```yaml
global:
  mention_notify_control: true   # default: enable /nb notify
  # mention_notify_control: false  # alternative: disable the feature entirely
```

When disabled, all bound platforms always receive @mention notifications, and `/nb notify` commands return a disabled hint.
