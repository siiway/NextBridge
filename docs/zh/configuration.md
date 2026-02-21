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

```
{
  "<平台名>": {
    "<实例ID>": { ...驱动器配置... }
  }
}
```

| 层级 | 说明 |
|---|---|
| `<平台名>` | 取值为 `napcat`、`discord`、`telegram`、`feishu`、`dingtalk`、`yunhu`、`kook`、`matrix` 之一 |
| `<实例ID>` | 由你自由命名，在规则配置中用于引用此实例 |

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
