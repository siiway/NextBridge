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

### 配置验证

使用内置 validate 命令检查配置和规则的语法正确性，无需启动桥接：

```sh
# 使用默认数据路径验证
uv run main.py validate

# 指定自定义数据目录
uv run main.py validate -d my-data/

# 仅验证指定的配置文件
uv run main.py validate -c path/to/config.yaml

# 仅验证指定的规则文件
uv run main.py validate -r path/to/rules.json

# 显式指定两者路径
uv run main.py validate --config config.yaml --rules rules.yaml
```

退出码：
- **0** — 验证通过
- **1** — 发现语法/格式错误
- **2** — 手动指定的文件未找到

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
| `<平台名>` | 取值为 `qq`、`discord`、`telegram`、`feishu`、`dingtalk`、`yunhu`、`kook`、`vocechat`、`matrix`、`signal`、`teams`、`googlechat`、`slack`、`mattermost`、`rocketchat`、`webhook` 之一 |
| `<实例ID>` | 由你自由命名，在规则配置中用于引用此实例 |

## 全局配置

`global` 部分包含适用于所有驱动的配置选项，除非在特定驱动配置中被覆盖。

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `proxy` | 否 | — | 全局代理 URL，适用于所有***支持代理配置***的驱动（例如：`http://proxy.example.com:8080`）。单个驱动的代理设置将覆盖此全局设置。 |
| `strict_echo_match` | 否 | `false` | 控制 NextBridge 防止 echo (回声) 到同一个频道/实例的行为。当为 `false`（默认）时，如果目标实例 ID 或频道与源消息相同，则跳过；当为 `true` 时，只有当目标实例 ID 和频道都与源消息相同时才跳过。默认为 `false` 以最大程度防止回声。 |
| `fuzzy_mention_match` | 否 | `false` | 控制在没有精确绑定映射时，是否回退使用昵称进行模糊匹配。当为 `true` 时，会尝试将提及用户的名称与目标平台中已知的显示名称进行匹配。当为 `false`（默认）时，仅精确的 ID 绑定或原生平台内的提及有效。默认为 `false`。 |
| `sanitize_nickname` | 否 | `true` | 是否在桥接前删除发送者昵称中的不可见字符。当为 `true`（默认）时，会从 `nickname`/`username`、richheader 标题以及 QQ 合并转发节点发送者昵称中删除控制字符、零宽/格式字符（包括 `U+200B`–`U+200F` 与双向控制符）、变体选择符以及行/段分隔符，从而避免诸如 `&` + `U+200B` + `killjsj` 这类昵称在桥接时干扰输出。仅当某平台确实需要在昵称中保留不可见字符时才应关闭。 |
| `command_prefix` | 否 | `"nb"` | 内置桥接指令的前缀（不含前导 `/`）。例如将 `/nb bind` 改为 `/<前缀> bind`。 |
| `send_timeout` | 否 | `2.0` | 单条消息发送允许的最长时间（秒）。超过该时间后，消息会被转至后台慢发送队列，不再阻塞后续消息；该慢消息会在后台继续发送。慢发送任务默认由 4 个后台 worker 并发处理。QQ qid 会在消息转发后由后台查询并持久化。 |
| `base_url` | 否 | — | 生成外部可访问链接时使用的公共基础 URL（如 QQ 合并转发页面链接）。示例：`https://bridge.example.com` |
| `log` | 否 | — | 日志配置，用于控制日志输出和轮换。参见下方[日志配置](#日志配置)。 |
| `database` | 否 | — | 数据库配置，用于存储消息和用户映射。参见下方[数据库配置](#数据库配置)。 |
| `http` | 否 | — | 共享 HTTP 服务器配置，用于挂载驱动器 Webhook。参见下方 [HTTP 服务器配置](#http-服务器配置)。 |
| `plugins` | 否 | — | 插件发现与驱动器生命周期配置。参见下方 [插件配置](#插件配置)。 |
| `metrics` | 否 | — | 运行时指标统计配置。参见下方 [指标配置](#指标配置)。 |
| `middleware` | 否 | — | 消息中间件配置。参见下方 [中间件配置](#中间件配置)。 |

```json
{
  "global": {
    "proxy": "http://proxy.example.com:8080"
  }
}
```

::: tip 使用环境变量中的代理
 如果未设置，程序会尝试从环境变量 `http_proxy`, `https_proxy`, `all_proxy` 中读取代理配置 (不分大小写)，此时你可以通过将 `proxy` 指定为特殊值 `disabled` 来阻止使用系统代理。
:::

## 日志配置

NextBridge 使用 loguru 进行日志记录，支持灵活的日志输出和轮换。日志配置控制控制台输出和文件日志行为。

### 配置选项

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `log.level` | 否 | `INFO` | NextBridge 自身模块的控制台日志级别。第三方库的标准库 logging 默认保持 `INFO`，因此开启 `DEBUG` 不会让依赖库的请求/调试日志刷屏。 |
| `log.file_level` | 否 | `DEBUG` | 文件日志级别。默认为 DEBUG 以在故障排除时获取详细输出。 |
| `log.dir` | 否 | `null` | 日志文件目录路径。如果为 `null` 或未指定，则禁用文件日志。日志文件将自动以时间戳命名创建在指定目录中。 |
| `log.rotation_size` | 否 | `100 MB` | 单个日志文件的最大大小，超过此大小将自动轮换（例如：`"100 MB"`、`"500 MB"`）。 |
| `log.retention_days` | 否 | `7` | 保留日志文件的天数。超过此天数的旧日志文件将被自动删除。设置为 `0` 可禁用自动删除。 |
| `log.compression` | 否 | `zip` | 轮换后日志文件的压缩格式（例如：`"zip"`、`"gz"`、`"tar.gz"`）。设置为 `null` 可禁用压缩。 |
| `log.show_source` | 否 | `"auto"` | 控制日志中是否显示源文件位置。`"auto"`：仅在 DEBUG/TRACE 级别显示。`"always"`：始终显示。`"never"`：从不显示。 |

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
| `database.url` | 否 | `sqlite:///data.db` | SQLAlchemy 数据库 URL。SQLite 相对路径会按 `data/` 目录解析。 |
| `database.echo` | 否 | `false` | 启用 SQLAlchemy 查询日志用于调试。 |
| `database.pool_size` | 否 | — | 非 SQLite 数据库的连接池大小。未指定时使用 SQLAlchemy 默认值。 |
| `database.max_overflow` | 否 | — | 非 SQLite 数据库的连接池最大溢出大小。未指定时使用 SQLAlchemy 默认值。 |
| `database.pool_recycle` | 否 | `3600` | 连接回收时间（秒），默认为 1 小时。 |
| `database.sslmode` | 否 | — | PostgreSQL SSL 模式（如 `require`、`prefer`、`disable`）。仅适用于 PostgreSQL。 |
| `database.connect_timeout` | 否 | — | PostgreSQL 连接超时（秒）。仅适用于 PostgreSQL。 |
| `database.application_name` | 否 | — | PostgreSQL 应用名称，用于连接标识。仅适用于 PostgreSQL。 |
| `database.message_mapping_retention_days` | 否 | `30` | 消息映射保留天数。启动时及保存映射期间最多每小时删除一次更早的记录；设置为 `0` 可禁用清理。 |

### 数据库 URL 示例

**SQLite（默认）：**
```json
{
  "global": {
    "database": {
      "url": "sqlite:///data.db"
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
      "pool_recycle": 3600,
      "sslmode": "require",
      "connect_timeout": 10,
      "application_name": "nextbridge"
    }
  }
}
```

::: tip SQLite 路径处理
  使用 SQLite 的相对路径（如 `sqlite:///data.db`）时，路径将相对于数据目录（`data/`）解析。绝对路径（如 `sqlite:////var/lib/nextbridge/data.db`）将按原样使用。
:::

::: warning 连接池
  连接池设置（`pool_size`、`max_overflow`、`pool_recycle`）仅适用于非 SQLite 数据库。SQLite 使用基于文件的存储，不支持同样的连接池机制。
:::

## HTTP 服务器配置

部分驱动器（钉钉、飞书、VoceChat、云湖等）通过 HTTP Webhook 接收消息。NextBridge 运行一个共享的 HTTP 服务器（FastAPI/uvicorn），挂载所有 Webhook 端点。

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `http.host` | 否 | `"0.0.0.0"` | 共享 HTTP 服务器绑定的主机/IP |
| `http.port` | 否 | `9080` | 共享 HTTP 服务器端口 |
| `http.root_path` | 否 | `""` | ASGI `root_path`，在带路径前缀的反向代理后使用 |
| `http.log_level` | 否 | `"info"` | Uvicorn 日志级别（`critical`、`error`、`warning`、`info`、`debug`） |
| `http.enable` | 否 | `"unset"` | HTTP 服务器启动模式。`"unset"`：当有驱动器挂载子应用时自动启动。`"true"`：始终启动。`"false"`：从不启动。 |

```json
{
  "global": {
    "http": {
      "host": "0.0.0.0",
      "port": 9080
    }
  }
}
```

## 插件配置

控制驱动器与通用插件的发现、生命周期管理和每个插件的独立设置。

### 驱动器选择

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `plugins.drivers.enabled` | 否 | `[]` | 要加载的驱动器名称。空列表 = 从配置文件键自动发现 |
| `plugins.drivers.external` | `dict` | `{}` | 外部驱动器导入，按名称键值 |

#### 外部驱动器

NextBridge 从四个来源加载驱动器（优先级高者覆盖低者）：

| 来源 | 方式 |
|---|---|
| Pip 包（入口点） | 包声明 `nextbridge.drivers` 入口点——自动发现，无需配置 |
| Pip 包（显式） | 在 `plugins.drivers.external` 中声明模块（见下） |
| 本地文件 | 将 `<platform>.py` 放入 `plugins.paths` 列出的目录（文件名 = 平台名） |
| 内置 | NextBridge 自带的 `drivers/<platform>.py` |

驱动器模块必须在导入时调用 `drivers.registry.register()`，与内置驱动器使用
相同契约。若名称与内置驱动器冲突，外部来源会**覆盖**内置。外部驱动器还会
通过 `drivers.registry.register_cli()` 向 CLI 添加子命令（例如配对命令），
这些子命令与内置驱动器一同在启动时发现。

Pip 包通过 `pyproject.toml` 声明驱动器：

```toml
[project.entry-points."nextbridge.drivers"]
myplatform = "nextbridge_myplatform.driver"
```

随后将包安装到 NextBridge 运行的环境中。对于镜像文件系统只读或临时的
Docker 部署，建议安装到挂载的数据目录并通过 `PYTHONPATH` 暴露（入口点
元数据在容器重建后依然有效）：

```bash
docker run --rm -v ./data:/app/data -e NEXTBRIDGE_DATA_PATH=/app/data \
  ghcr.io/siiway/nextbridge:latest \
  /app/.venv/bin/python -m pip install --target=/app/data/pylibs nextbridge-myplatform
```

```yaml
# docker-compose（或等价的 nix 容器配置）
volumes: [ "./data:/app/data" ]
environment:
  - NEXTBRIDGE_DATA_PATH=/app/data
  - PYTHONPATH=/app/data/pylibs
```

（直接 `pip install --no-deps nextbridge-myplatform` 到 `/app/.venv` 也可行，
但安装内容位于容器层，容器重建后会丢失。）

然后添加实例配置：

若不想依赖入口点自动发现，可显式固定模块：

```json
{
  "global": {
    "plugins": {
      "drivers": {
        "external": {
          "myplatform": { "module": "nextbridge_myplatform.driver" }
        }
      }
    }
  }
}
```

### 通用插件

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `plugins.general.enabled` | 否 | `[]` | 要启用的插件名称 |
| `plugins.general.external` | 否 | `{}` | 外部插件模块，按名称键值 |
| `plugins.config` | 否 | `{}` | 按插件名称键值的配置 |

### 路径与生命周期

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `plugins.paths` | 否 | `[]` | 扫描驱动器/插件 `.py` 文件的本地目录列表 |
| `plugins.auto_restart` | 否 | `true` | 崩溃的驱动器自动重启（指数退避） |
| `plugins.max_restart_attempts` | 否 | `5` | 崩溃驱动器放弃重启前的最大重试次数 |
| `plugins.health_check_interval` | 否 | `60` | 定期驱动器健康检查间隔（秒）。设为 `0` 禁用 |
| `plugins.admin.enable` | 否 | `false` | 启用管理 API（读端点 `/_nextbridge/{health,drivers,plugins,metrics,rules,config}` 与写端点 `/_nextbridge/admin/*`）。需同时设置 `password`；未启用时除 `health` 外全部不可达 |
| `plugins.admin.user` | 否 | `"admin"` | 管理 API 的用户名（HTTP Basic Auth） |
| `plugins.admin.password` | 否 | `""` | 管理 API 访问密码（HTTP Basic Auth）。`admin.enable` 为 `true` 时必填 |

```json
{
  "global": {
    "plugins": {
      "general": {
        "enabled": ["stats"]
      },
      "config": {
        "stats": {
          "interval": 300
        }
      },
      "auto_restart": true,
      "max_restart_attempts": 5,
      "admin": {
        "enable": true,
        "user": "admin",
        "password": "your-secret-password"
      }
    }
  }
}
```

## 指标配置

NextBridge 内置运行时指标计数器（消息收发数、规则命中数、发送失败/超时数、配置重载次数、驱动器重启次数）。内存为计数真源，并会周期性快照到数据库（`metrics_counters` 表），进程重启后继续累加。

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `metrics.enabled` | 否 | `true` | 是否启用指标收集与 `/_nextbridge/metrics` 端点 |
| `metrics.snapshot_interval` | 否 | `60` | 内存计数快照写入数据库的间隔（秒）。设为 `0` 可禁用周期持久化 |

```json
{
  "global": {
    "metrics": {
      "enabled": true,
      "snapshot_interval": 60
    }
  }
}
```

指标通过 `/_nextbridge/metrics` 以 Prometheus 文本格式暴露（需要管理 API 凭据）。详见[管理 API](./admin-api)。

## 热重载

部分配置可在运行时热重载（通过管理 API 或 `SIGHUP` 信号），无需重启进程：

- `command_prefix`
- `strict_echo_match`
- `fuzzy_mention_match`
- `mention_notify_control`
- `send_timeout`
- `sanitize_nickname`
- 规则文件（`rules.yaml` 等）
- 驱动器实例配置（会以新配置重建对应驱动器）

以下配置**需要重启**才能生效：`proxy`、`log.*`、`database.*`、`http.*`、`plugins.*`（含 `admin.*`）与 `middleware`。

## 中间件配置

消息中间件允许在消息发送前进行转换或过滤。中间件按列表顺序依次执行。

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `middleware.enabled` | 否 | `[]` | 要启用的中间件名称列表（按列表顺序执行） |

```json
{
  "global": {
    "middleware": {
      "enabled": ["example-middleware"]
    }
  }
}
```

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
  "qq": {
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

## 完整示例（YAML）

```yaml
qq:
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

各平台的详细配置项，请参阅[驱动器](./drivers/)章节中对应的驱动器页面。
