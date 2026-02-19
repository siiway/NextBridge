# 配置文件参考

NextBridge 通过 `data/config.json` 进行配置，文件采用两级结构：

```
{
  "<平台名>": {
    "<实例ID>": { ...驱动器配置... }
  }
}
```

| 层级 | 说明 |
|---|---|
| `<平台名>` | 取值为 `napcat`、`discord`、`telegram`、`feishu`、`dingtalk` 之一 |
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

## 完整示例

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

各平台的详细配置项，请参阅[驱动器](/zh/drivers/)章节中对应的驱动器页面。
