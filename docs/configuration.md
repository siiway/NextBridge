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
  "<platform>": {
    "<instance_id>": { ...driver config... }
  }
}
```

| Level | Description |
|---|---|
| `<platform>` | One of `napcat`, `discord`, `telegram`, `feishu`, `dingtalk`, `yunhu`, `kook`, `matrix`, `signal`, `slack` |
| `<instance_id>` | A name you choose freely — used to reference this instance in rules |

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
