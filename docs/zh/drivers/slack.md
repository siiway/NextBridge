# Slack

Slack 驱动器支持两种独立的接收模式和两种独立的发送模式，可自由组合配置。

## 接收模式

| 模式 | 所需配置 | 说明 |
|---|---|---|
| **Socket Mode** | `app_token` | NextBridge 主动向 Slack 建立 WebSocket 连接，无需公网 URL。 |
| **Events API** | `signing_secret` + `listen_port` | Slack 将事件 POST 到你的 HTTP 端点，需要公网 URL。 |

若同时配置了 `app_token`，将优先使用 Socket Mode，Events API 配置会被忽略。

## 发送模式

| 模式 | 配置键 | 说明 |
|---|---|---|
| **Bot**（默认） | `send_method: "bot"` | 通过 `chat.postMessage` 发送消息，支持文件上传。 |
| **Incoming Webhook** | `send_method: "webhook"` | POST 到固定的 Incoming Webhook URL，仅支持文字，`channel_id` 无效。 |

---

## Socket Mode 准备工作

1. 前往 [api.slack.com/apps](https://api.slack.com/apps) 创建一个新应用（从头创建）。
2. 在 **Socket Mode** 下启用 Socket Mode，并生成一个带有 `connections:write` 权限的**应用级令牌（App-level token）**，该令牌以 `xapp-` 开头。
3. 在 **OAuth & Permissions** 下，为 Bot Token 添加以下权限范围：
   - `channels:history`、`groups:history` — 读取消息
   - `chat:write` — 发送消息
   - `files:read` — 下载接收到的文件
   - `files:write` — 上传文件
   - `users:read` — 解析显示名称
4. 在 **Event Subscriptions** 下启用事件，并订阅：
   - `message.channels` — 公开频道消息
   - `message.groups` — 私有频道消息
5. 将应用安装到你的工作区，复制 **Bot User OAuth Token**（`xoxb-...`）。
6. 在每个需要桥接的频道中邀请机器人（`/invite @YourBot`）。

## Events API 准备工作

1. 在 [api.slack.com/apps](https://api.slack.com/apps) 创建 Slack 应用。
2. 在 **OAuth & Permissions** 下，添加上述相同的 Bot Token 权限范围。
3. 在 **Event Subscriptions** 下启用事件，将**请求 URL** 设置为你的公网端点（如 `https://example.com/slack/events`）。
4. 订阅 `message.channels` 和 `message.groups` 机器人事件。
5. 在 **Basic Information** 下复制 **Signing Secret**（用于验证请求合法性）。
6. 安装应用并复制 Bot Token。

## Incoming Webhook 准备工作（仅发送）

1. 在你的 Slack 应用中，进入 **Incoming Webhooks** 并启用。
2. 点击 **Add New Webhook to Workspace**，选择目标频道，复制 Webhook URL。

---

## 配置项

在配置文件的 `slack.<实例ID>` 下添加：

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `bot_token` | Bot 发送 / 文件下载时必填 | — | Bot User OAuth Token，以 `xoxb-` 开头 |
| `app_token` | Socket Mode 接收时必填 | — | 应用级令牌，以 `xapp-` 开头 |
| `send_method` | 否 | `"bot"` | `"bot"` 或 `"webhook"` |
| `incoming_webhook_url` | Webhook 发送时必填 | — | Slack Incoming Webhook URL |
| `signing_secret` | Events API 接收时必填 | — | Slack 签名密钥，用于验证请求 |
| `listen_port` | Events API 接收时必填 | — | HTTP 监听端口 |
| `listen_path` | 否 | `"/slack/events"` | Events API 端点的 HTTP 路径 |
| `max_file_size` | 否 | `52428800`（50 MB） | 发送附件时单个文件的最大字节数 |

### Socket Mode 接收 + Bot 发送（无需公网 URL）

```json
{
  "slack": {
    "sl_main": {
      "bot_token": "xoxb-...",
      "app_token": "xapp-..."
    }
  }
}
```

### Events API 接收 + Incoming Webhook 发送

```json
{
  "slack": {
    "sl_main": {
      "signing_secret": "abc123...",
      "listen_port": 8090,
      "send_method": "webhook",
      "incoming_webhook_url": "https://hooks.slack.com/services/T.../B.../..."
    }
  }
}
```

### Events API 接收 + Bot 发送

```json
{
  "slack": {
    "sl_main": {
      "bot_token": "xoxb-...",
      "signing_secret": "abc123...",
      "listen_port": 8090
    }
  }
}
```

### 仅 Incoming Webhook 发送（无接收）

```json
{
  "slack": {
    "sl_main": {
      "send_method": "webhook",
      "incoming_webhook_url": "https://hooks.slack.com/services/T.../B.../..."
    }
  }
}
```

## 规则频道键

| 键 | 说明 |
|---|---|
| `channel_id` | Slack 频道 ID，例如 `C1234567890` |

获取频道 ID 的最简方式：在 Slack 中打开该频道，点击顶部频道名称，弹窗底部会显示 ID。

> **注意：** `channel_id` 仅用于**接收侧路由**和 **Bot 发送**。当 `send_method` 为 `"webhook"` 时，目标频道由 Webhook URL 决定，`channel_id` 会被忽略。

```json
{
  "sl_main": {
    "channel_id": "C1234567890"
  }
}
```

## 注意事项

- Bot 消息和系统消息（加入、编辑等）会被自动忽略，防止消息回显。
- 无论使用哪种接收模式，下载文件均需要 `bot_token`。
- 当 `send_method` 为 `"webhook"` 时，若消息包含附件且已配置 `bot_token`，会自动回退到 Bot 模式发送（通过 `chat_postMessage` + `files_upload_v2`）；若未配置 `bot_token`，附件将以文字标签形式发送。
- 用户显示名称通过 Users API（需要 `bot_token`）解析，并在进程生命周期内缓存。
- Events API 请求超过 5 分钟的将被拒绝，以防止重放攻击。
