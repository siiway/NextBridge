# 云湖（Yunhu）

云湖驱动器通过 Webhook HTTP 服务器接收消息，并通过云湖开放 API 发送消息。

## 准备工作

1. 前往[云湖开发者平台](https://www.yunhuim.com/)创建一个机器人。
2. 复制机器人 Token。
3. 将机器人的 Webhook 地址设置为 `http://<你的服务器>:<webhook_port><webhook_path>`（例如 `http://1.2.3.4:8765/yunhu-webhook`）。
4. 将机器人添加到你的群组。
5. 记录群组的 Chat ID（可在群组设置中查看，或从传入 Webhook 事件的 `message.chatId` 字段获取）。

## 配置项

在 `config.json` 的 `yunhu.<实例ID>` 下添加：

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `token` | 是 | — | 来自云湖开发者平台的机器人 Token |
| `webhook_port` | 否 | `8765` | 传入 Webhook HTTP 服务器的监听端口 |
| `webhook_path` | 否 | `"/yunhu-webhook"` | Webhook 端点的 HTTP 路径 |
| `proxy_host` | 否 | — | `cloudflare/yh-proxy.js` Worker 的基础 URL。启用两项功能：头像 URL 改写为 `<host>/pfp?url=…`（注入必要的 Referer）；Discord CDN 附件 URL 改写为 `<host>/media?url=…`，使云湖服务器在中国境内也能拉取。 |

::: tip 公共端点
 `https://yh-proxy.siiway.top` 是 `cloudflare/yh-proxy.js` 的托管实例，可直接使用，无需自行部署 Worker。
:::

```json
{
  "yunhu": {
    "yh_main": {
      "token": "your-yunhu-bot-token",
      "webhook_port": 8765,
      "webhook_path": "/yunhu-webhook",
      "proxy_host": "https://yh-proxy.siiway.top"
    }
  }
}
```

## 规则频道键

在 `rules.json` 的 `channels` 或 `from`/`to` 下使用：

| 键 | 说明 |
|---|---|
| `chat_id` | 云湖群组（或用户）的 Chat ID |
| `chat_type` | `"group"`（默认）或 `"user"` |

```json
{
  "yh_main": { "chat_id": "your-group-chat-id", "chat_type": "group" }
}
```

## 接收的消息类型

| 云湖消息类型 | 附件类型 |
|---|---|
| `text` / `markdown` | — （纯文本） |
| `image` | `image` |
| `video` | `video` |
| `file` | `file` |

## 发送

每条传出消息会拆分为一次或多次云湖 API 调用：

| 附件类型 | 云湖 contentType | 说明 |
|---|---|---|
| `image` | `image` | 云湖服务端拉取 URL 并渲染为内联图片 |
| `video` | `video` | 渲染为内联视频播放器 |
| `voice` / `file` | `file` | 渲染为可下载的文件链接 |
| （无 URL） | `text` | 将 `[类型: 文件名]` 文本回退追加到文字消息中 |

文字部分（包含富头部前缀）优先发送，随后每个附件单独发送。

## 注意事项

- 云湖必须能够从外网访问 Webhook 地址。若运行在 NAT 环境后，请使用反向代理或 `ngrok` 等隧道工具。
- 每个 NextBridge 实例绑定一个独立端口。如果配置了多个云湖实例，请为每个实例设置不同的 `webhook_port`。
- 机器人 Token 以查询参数（`?token=…`）形式随每次发送请求发出，请妥善保管。
