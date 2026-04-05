> 本文档由 AI 编写，已经人工审核。

# 配置文件参考

## 配置文件格式

NextBridge 支持 **JSON**、**YAML** 和 **TOML** 格式的配置文件。将配置文件放在数据目录（默认为 `data/`）下，程序会按以下顺序查找并使用第一个存在的文件：

1. `config.json`
2. `config.yaml` / `config.yml`
3. `config.toml`

### 格式转换

使用内置 convert 命令可以在各格式之间互转：

```sh
uv run main.py convert data/config.json data/config.yaml
uv run main.py convert data/config.yaml data/config.toml
```

## 结构

无论使用哪种格式，配置文件均采用两级结构：

```jsonc
{
  "global": {
    // ... 全局配置 ...
  },
  "<平台名>": {
    "<实例ID>": {
      // ... 驱动器配置 ...
    }
  }
}
```

| 层级 | 说明 |
|---|---|
| `global` | 全局配置选项，适用于所有驱动，除非在特定驱动配置中被覆盖 |
| `<平台名>` | 取值为 `napcat`、`discord`、`telegram`、`feishu`、`dingtalk`、`yunhu`、`kook`、`vocechat`、`matrix`、`signal`、`teams`、`googlechat`、`slack`、`mattermost`、`rocketchat`、`webhook` 之一 |
| `<实例ID>` | 由你自由命名，在规则配置中用于引用此实例 |

## 全局配置

`global` 部分包含适用于所有驱动的配置选项，除非在特定驱动配置中被覆盖。

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `command_prefix` | 否 | `nb` | 内置桥接命令的前缀。使用默认前缀时，命令写作 `/nb bind setup`、`/nb bind confirm <code>`、`/nb bind rm` 和 `/nb bind list`。 |
| `proxy` | 否 | — | 全局代理 URL，适用于所有***支持代理配置***的驱动（例如：`http://proxy.example.com:8080`）。单个驱动的代理设置将覆盖此全局设置。 |
| `strict_echo_match` | 否 | `false` | 控制 NextBridge 防止 echo (回声) 到同一个频道/实例的行为。当为 `false`（默认）时，如果目标实例 ID 或频道与源消息相同，则跳过；当为 `true` 时，只有当目标实例 ID 和频道都与源消息相同时才跳过。默认为 `false` 以最大程度防止回声。 |
| `http` | 否 | — | 所有 Webhook 驱动共用的 HTTP 服务配置。参见下方[HTTP 服务配置](#http-服务配置)。 |
| `log` | 否 | — | 日志配置，用于控制日志输出和轮换。参见下方[日志配置](#日志配置)。 |
| `database` | 否 | — | 数据库配置，用于存储消息和用户映射。参见下方[数据库配置](#数据库配置)。 |

```json
{
  "global": {
    "command_prefix": "nb",
    "proxy": "http://proxy.example.com:8080"
  }
}
```

::: tip 使用环境变量中的代理
 如果未设置，程序会尝试从环境变量 `http_proxy`, `https_proxy`, `all_proxy` 中读取代理配置 (不分大小写)，此时你可以通过将 `proxy` 指定为特殊值 `disabled` 来阻止使用系统代理。
:::

## HTTP 服务配置

NextBridge 现在为所有需要入站 Webhook 的驱动提供**单一共享 FastAPI/uvicorn HTTP 服务**。各驱动通过路径挂载自己的子应用。

- 只有在至少有一个驱动挂载子应用时，HTTP 服务才会启动。
- 驱动侧的路径配置（如 `listen_path`、`webhook_path`）仍然保留并生效。

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `http.enable` | 否 | `unset` | 启动模式：`unset`（自动）、`true`（强制开）、`false`（强制关） |
| `http.host` | 否 | `0.0.0.0` | 共享 HTTP 服务监听的主机/IP |
| `http.port` | 否 | `8090` | 共享 HTTP 服务监听端口 |
| `http.root_path` | 否 | `""` | 反向代理使用路径前缀时的 ASGI `root_path` |
| `http.log_level` | 否 | `info` | Uvicorn 日志级别（`critical`/`error`/`warning`/`info`/`debug`） |

```json
{
  "global": {
    "http": {
      "enable": "unset",
      "host": "0.0.0.0",
      "port": 8090,
      "root_path": "",
      "log_level": "info"
    }
  }
}
```

`http.enable` 行为：
- `unset`：仅当至少有一个驱动挂载 webhook 子应用时启动
- `true`：始终启动 HTTP 服务
- `false`：始终关闭 HTTP 服务；若驱动挂载了 webhook，会记录告警且入站 webhook 功能不可用

健康检查端点：`/_nextbridge/health`
- 始终返回 `status` 与 `version`
- 仅当 `http.log_level` 为 `debug` 时返回 `mounts`

## 日志配置

NextBridge 使用 loguru 进行日志记录，支持灵活的日志输出和轮换。日志配置控制控制台输出和文件日志行为。

### 配置选项

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `log.level` | 否 | `INFO` | 控制台日志级别。 |
| `log.file_level` | 否 | `DEBUG` | 文件日志级别。默认为 DEBUG 以在故障排除时获取详细输出。 |
| `log.dir` | 否 | `null` | 日志文件目录路径。如果为 `null` 或未指定，则禁用文件日志。日志文件将自动以时间戳命名创建在指定目录中。 |
| `log.rotation_size` | 否 | `100 MB` | 单个日志文件的最大大小，超过此大小将自动轮换（例如：`"100 MB"`、`"500 MB"`）。 |
| `log.retention_days` | 否 | `7` | 保留日志文件的天数。超过此天数的旧日志文件将被自动删除。设置为 `0` 可禁用自动删除。 |
| `log.compression` | 否 | `zip` | 轮换后日志文件的压缩格式（例如：`"zip"`、`"gz"`、`"tar.gz"`）。设置为 `null` 可禁用压缩。 |

### 配置示例

**基础日志（仅控制台）：**
```json
{
  "global": {
    "log": {
      "level": "INFO"
    }
  }
}
```

**带轮换的文件日志：**
```json
{
  "global": {
    "log": {
      "level": "INFO",
      "dir": "logs",
      "rotation_size": "100 MB",
      "retention_days": 7,
      "compression": "zip"
    }
  }
}
```

**调试用的详细日志：**
```json
{
  "global": {
    "log": {
      "level": "DEBUG",
      "dir": "logs",
      "rotation_size": "50 MB",
      "retention_days": 3,
      "compression": null
    }
  }
}
```

::: tip 日志轮换
  当设置了 `log.dir` 时，日志文件在超过 `log.rotation_size` 大小时会自动轮换。超过 `log.retention_days` 天数的旧日志文件会被自动删除。可以使用 `log.compression` 压缩轮换后的文件以节省磁盘空间。
:::

## 数据库配置

NextBridge 使用 SQLAlchemy 进行数据库操作，支持多种数据库后端，包括 SQLite、MySQL、PostgreSQL 等。数据库用于存储：

- 不同平台之间的消息 ID 映射
- 用于跨平台用户识别的用户绑定
- 用户显示名称映射
- 临时绑定码

### 配置选项

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `database.url` | 否 | `sqlite:///messages.db` | SQLAlchemy 数据库 URL。SQLite 相对路径会按 `data/` 目录解析。 |
| `database.echo` | 否 | `false` | 启用 SQLAlchemy 查询日志用于调试。 |
| `database.pool_size` | 否 | — | 非 SQLite 数据库的连接池大小。未指定时使用 SQLAlchemy 默认值。 |
| `database.max_overflow` | 否 | — | 非 SQLite 数据库的连接池最大溢出大小。未指定时使用 SQLAlchemy 默认值。 |
| `database.pool_recycle` | 否 | `3600` | 连接回收时间（秒），默认为 1 小时。 |

### 数据库 URL 示例

**SQLite（默认）：**
```json
{
  "global": {
    "database": {
      "url": "sqlite:///messages.db"
    }
  }
}
```

**MySQL：**
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

**PostgreSQL：**
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

::: tip SQLite 路径处理
  使用 SQLite 的相对路径（如 `sqlite:///messages.db`）时，路径将相对于数据目录（`data/`）解析。绝对路径（如 `sqlite:////var/lib/nextbridge/messages.db`）将按原样使用。
:::

::: warning 连接池
  连接池设置（`pool_size`、`max_overflow`、`pool_recycle`）仅适用于非 SQLite 数据库。SQLite 使用基于文件的存储，不支持同样的连接池机制。
:::

同一平台可以**运行多个实例**，只需在平台名下添加多个键：

```json
{
  "discord": {
    "服务器A": { "bot_token": "...", "webhook_url": "..." },
    "服务器B": { "bot_token": "...", "webhook_url": "..." }
  }
}
```

## 完整示例（JSON）

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
      "listen_path": "/event"
    }
  },
  "dingtalk": {
    "dt_main": {
      "app_key": "dingxxxx",
      "app_secret": "xxxx",
      "robot_code": "xxxx",
      "signing_secret": "xxxx",
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

## 完整示例（YAML）

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

各平台的详细配置项，请参阅[驱动器](/zh/drivers/)章节中对应的驱动器页面。
