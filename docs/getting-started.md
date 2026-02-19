# Getting Started

## Requirements

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — the Python package manager used by NextBridge

## Installation

**1. Clone the repository**

```bash
git clone https://github.com/siiway/NextBridge.git
cd NextBridge
```

**2. Install dependencies**

```bash
uv sync
```

This installs all required packages (`discord-py`, `websockets`, `aiohttp`, `python-telegram-bot`, `lark-oapi`, `alibabacloud-dingtalk`) into an isolated virtual environment.

## Configure

NextBridge reads two JSON files from the `data/` directory.

### data/config.json

Declare each platform instance with its credentials. Every key under a platform name is an **instance ID** you freely choose — it is referenced in rules later.

```json
{
  "napcat": {
    "my_qq": {
      "ws_url": "ws://127.0.0.1:3001",
      "ws_token": "your_token"
    }
  },
  "discord": {
    "my_dc": {
      "send_method": "webhook",
      "webhook_url": "https://discord.com/api/webhooks/...",
      "bot_token": "your_bot_token"
    }
  },
  "telegram": {
    "my_tg": {
      "bot_token": "123456:ABC..."
    }
  }
}
```

See the [Drivers](/drivers/) section for every config key each platform supports.

### data/rules.json

Define how messages flow between instances. The simplest setup uses a **connect** rule, which links all listed channels bidirectionally:

```json
{
  "rules": [
    {
      "type": "connect",
      "channels": {
        "my_qq":  { "group_id": "123456789" },
        "my_dc":  { "server_id": "111", "channel_id": "222" },
        "my_tg":  { "chat_id": "-100987654321" }
      },
      "msg": {
        "msg_format": "{user} @ {from}: {msg}"
      }
    }
  ]
}
```

See [Rules](/rules) for the full reference.

## Run

```bash
uv run main.py
```

Press **Ctrl+C** to stop gracefully.

## Project layout

```
NextBridge/
├── data/
│   ├── config.json   # credentials & connection settings
│   └── rules.json    # message routing rules
├── drivers/          # one file per supported platform
├── services/         # shared utilities (bridge engine, media, logger…)
└── main.py           # entry point
```
