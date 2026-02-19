# 快速开始

## 环境要求

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — NextBridge 使用的 Python 包管理器

## 安装

**1. 克隆仓库**

```bash
git clone https://github.com/siiway/NextBridge.git
cd NextBridge
```

**2. 安装依赖**

```bash
uv sync
```

此命令会将所有依赖（`discord-py`、`websockets`、`aiohttp`、`python-telegram-bot`、`lark-oapi`、`alibabacloud-dingtalk`）安装到独立的虚拟环境中。

## 配置

NextBridge 从 `data/` 目录读取两个 JSON 配置文件。

### data/config.json

在此声明每个平台的实例及其凭据。平台名下的每个键是你自由命名的**实例 ID**，后续在规则中引用。

```json
{
  "napcat": {
    "我的QQ": {
      "ws_url": "ws://127.0.0.1:3001",
      "ws_token": "your_token"
    }
  },
  "discord": {
    "我的Discord": {
      "send_method": "webhook",
      "webhook_url": "https://discord.com/api/webhooks/...",
      "bot_token": "your_bot_token"
    }
  },
  "telegram": {
    "我的TG": {
      "bot_token": "123456:ABC..."
    }
  }
}
```

每个平台支持的配置项请参阅[驱动器](/zh/drivers/)章节。

### data/rules.json

在此定义消息在实例之间的流向。最简单的方式是使用 **connect** 规则，将所有列出的频道双向连通：

```json
{
  "rules": [
    {
      "type": "connect",
      "channels": {
        "我的QQ":      { "group_id": "123456789" },
        "我的Discord": { "server_id": "111", "channel_id": "222" },
        "我的TG":      { "chat_id": "-100987654321" }
      },
      "msg": {
        "msg_format": "{user} @ {from}: {msg}"
      }
    }
  ]
}
```

完整说明请参阅[规则配置](/zh/rules)。

## 运行

```bash
uv run main.py
```

按 **Ctrl+C** 可优雅地停止程序。

## 项目结构

```
NextBridge/
├── data/
│   ├── config.json   # 凭据与连接配置
│   └── rules.json    # 消息路由规则
├── drivers/          # 每个平台对应一个驱动器文件
├── services/         # 公共工具（桥接引擎、媒体下载、日志…）
└── main.py           # 程序入口
```
