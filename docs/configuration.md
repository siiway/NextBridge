# Configuration Reference

NextBridge is configured through `data/config.json`. The file has a two-level structure:

```
{
  "<platform>": {
    "<instance_id>": { ...driver config... }
  }
}
```

| Level | Description |
|---|---|
| `<platform>` | One of `napcat`, `discord`, `telegram`, `feishu`, `dingtalk` |
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

## Full example

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
  }
}
```

For per-driver config keys, see the individual driver pages in the [Drivers](/drivers/) section.
