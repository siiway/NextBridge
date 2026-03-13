# Configuration Reference

## Config file formats

NextBridge supports **JSON**, **YAML**, and **TOML** config files. Place the file in the data directory (default: `data/`). The first file found in this order is used:

1. `config.json`
2. `config.yaml` / `config.yml`
3. `config.toml`

### Converting between formats

Use the built-in convert command to translate between formats:

```sh
uv run main.py convert data/config.json data/config.yaml
uv run main.py convert data/config.yaml data/config.toml
```

## Structure

The config has a two-level structure regardless of format:

```
{
  "global": { ...global config... },
  "<platform>": {
    "<instance_id>": { ...driver config... }
  }
}
```

| Level | Description |
|---|---|
| `global` | Global configuration options that apply to all drivers unless overridden |
| `<platform>` | One of `napcat`, `discord`, `telegram`, `feishu`, `dingtalk`, `yunhu`, `kook`, `matrix`, `signal`, `slack` |
| `<instance_id>` | A name you choose freely — used to reference this instance in rules |

## Global Configuration

The `global` section contains configuration options that apply to all drivers unless overridden in the driver-specific configuration.

| Key | Required | Default | Description |
|---|---|---|---|
| `proxy` | No | — | Global proxy URL for all drivers that ***support proxy configuration*** (e.g., `http://proxy.example.com:8080`). Individual driver proxy settings will override this global setting. |
| `strict_echo_match` | No | `false` | Controls how NextBridge prevents echoing messages back to the same channel/instance. When `false` (default), skips if target_id == msg.instance_id OR target_channel == msg.channel. When `true`, skips only if target_id == msg.instance_id AND target_channel == msg.channel. Default is `false` to maximize echo prevention. |
| `database` | No | — | Database configuration for storing message and user mappings. See [Database Configuration](#database-configuration) below. |

```json
{
  "global": {
    "proxy": "http://proxy.example.com:8080"
  }
}
```

::: tip Using proxy from environment variables
 If not set, the program will attempt to read proxy configuration from environment variables `http_proxy`, `https_proxy`, and `all_proxy` (case-insensitive). You can disable the use of system proxy by setting `proxy` to the special value `disabled`.
:::

## Database Configuration

NextBridge uses SQLAlchemy for database operations, which supports multiple database backends including SQLite, MySQL, PostgreSQL, and more. The database is used to store:

- Message ID mappings between different platforms
- User bindings for cross-platform user identification
- User display name mappings
- Temporary binding codes

### Configuration Options

| Key | Required | Default | Description |
|---|---|---|---|
| `database.url` | No | `sqlite:///data/messages.db` | SQLAlchemy database URL. See examples below for different databases. |
| `database.echo` | No | `false` | Enable SQLAlchemy query logging for debugging. |
| `database.pool_size` | No | — | Connection pool size for non-SQLite databases. Uses SQLAlchemy default if not specified. |
| `database.max_overflow` | No | — | Maximum overflow size of the pool for non-SQLite databases. Uses SQLAlchemy default if not specified. |
| `database.pool_recycle` | No | `3600` | Recycle connections after this many seconds (default: 1 hour). |

### Database URL Examples

**SQLite (default):**
```json
{
  "global": {
    "database": {
      "url": "sqlite:///data/messages.db"
    }
  }
}
```

**MySQL:**
```json
{
  "global": {
    "database": {
      "url": "mysql+pymysql://user:password@localhost:3306/nextbridge",
      "pool_size": 10,
      "max_overflow": 20,
      "pool_recycle": 3600
    }
  }
}
```

**PostgreSQL:**
```json
{
  "global": {
    "database": {
      "url": "postgresql://user:password@localhost:5432/nextbridge",
      "pool_size": 10,
      "max_overflow": 20,
      "pool_recycle": 3600
    }
  }
}
```

::: tip SQLite Path Handling
  When using SQLite with a relative path (e.g., `sqlite:///data/messages.db`), the path is resolved relative to the data directory. Absolute paths (e.g., `sqlite:////var/lib/nextbridge/messages.db`) are used as-is.
:::

::: warning Connection Pooling
  Connection pool settings (`pool_size`, `max_overflow`, `pool_recycle`) only apply to non-SQLite databases. SQLite uses a file-based storage and doesn't support connection pooling in the same way.
:::

You can run **multiple instances of the same platform** by adding more keys under the platform:

```json
{
  "discord": {
    "server_a": { "bot_token": "...", "webhook_url": "..." },
    "server_b": { "bot_token": "...", "webhook_url": "..." }
  }
}
```

## Full example (JSON)

```json
{
  "napcat": {
    "qq_main": {
      "ws_url": "ws://127.0.0.1:3001",
      "ws_token": "secret"
    }
  },
  "discord": {
    "dc_main": {
      "send_method": "webhook",
      "webhook_url": "https://discord.com/api/webhooks/ID/TOKEN",
      "bot_token": "BOT_TOKEN",
      "max_file_size": 8388608
    }
  },
  "telegram": {
    "tg_main": {
      "bot_token": "123456:ABC-DEF",
      "max_file_size": 52428800
    }
  },
  "feishu": {
    "fs_main": {
      "app_id": "cli_xxxx",
      "app_secret": "xxxx",
      "verification_token": "xxxx",
      "encrypt_key": "",
      "listen_port": 8080,
      "listen_path": "/event"
    }
  },
  "dingtalk": {
    "dt_main": {
      "app_key": "dingxxxx",
      "app_secret": "xxxx",
      "robot_code": "xxxx",
      "signing_secret": "xxxx",
      "listen_port": 8082,
      "listen_path": "/dingtalk/event"
    }
  },
  "matrix": {
    "mx_main": {
      "homeserver": "https://matrix.org",
      "user_id": "@mybot:matrix.org",
      "password": "your_password"
    }
  },
  "signal": {
    "sg_main": {
      "api_url": "http://localhost:8080",
      "number": "+12025551234"
    }
  },
  "slack": {
    "sl_main": {
      "bot_token": "xoxb-...",
      "app_token": "xapp-..."
    }
  }
}
```

## Full example (YAML)

```yaml
napcat:
  qq_main:
    ws_url: ws://127.0.0.1:3001
    ws_token: secret

discord:
  dc_main:
    send_method: webhook
    webhook_url: https://discord.com/api/webhooks/ID/TOKEN
    bot_token: BOT_TOKEN
    max_file_size: 8388608

matrix:
  mx_main:
    homeserver: https://matrix.org
    user_id: "@mybot:matrix.org"
    password: your_password
```

For per-driver config keys, see the individual driver pages in the [Drivers](/drivers/) section.
