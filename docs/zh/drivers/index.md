> 本文档由 AI 编写，已经人工审核。

# 驱动器概览

**驱动器**是 NextBridge 与具体聊天平台之间的适配层。每个驱动器负责接收来自该平台的消息，以及向该平台发送消息。

## 支持的平台

| 平台 | 驱动器 | 接收 | 发送 | 备注 |
|---|---|---|---|---|
| 腾讯 QQ | [NapCat](/zh/drivers/napcat) | ✅ | ✅ | 使用非官方 NapCat WebSocket 桥接方案 |
| Discord | [Discord](/zh/drivers/discord) | ✅ | ✅ | 通过 Bot 网关接收；通过 Webhook 或 Bot 发送 |
| Telegram | [Telegram](/zh/drivers/telegram) | ✅ | ✅ | 使用长轮询 |
| 飞书 / Lark | [飞书](/zh/drivers/feishu) | ✅ | ✅ | Webhook 接收；IM API 发送 |
| 钉钉 | [钉钉](/zh/drivers/dingtalk) | ✅ | ✅ | Webhook 接收；机器人 API 发送 |
| 云湖 | [云湖](/zh/drivers/yunhu) | ✅ | ✅ | Webhook 接收；开放 API 发送 |
| KOOK（开黑啦） | [KOOK](/zh/drivers/kook) | ✅ | ✅ | WebSocket 接收；机器人 API 发送；上传至 KOOK CDN |
| VoceChat | [VoceChat](/zh/drivers/vocechat) | ✅ | ✅ | |
| Matrix | [Matrix](/zh/drivers/matrix) | ✅ | ✅ | 客户端同步循环；暂不支持 E2E 加密 |
| Signal | [Signal](/zh/drivers/signal) | ✅ | ✅ | 需要 signal-cli REST API |
| Microsoft Teams | [Teams](/zh/drivers/teams) | ✅ | ✅ | Bot Framework 连接器 |
| Google Chat | [Google Chat](/zh/drivers/googlechat) | ✅ | ✅ | 使用服务账号的 REST API |
| Slack | [Slack](/zh/drivers/slack) | ✅ | ✅ | Socket Mode 或 Events API 接收；Bot 或 Webhook 发送 |
| Mattermost | [Mattermost](/zh/drivers/mattermost) | ✅ | ✅ | WebSocket 接收；REST API 发送 |
| Rocket.Chat | [Rocket.Chat](/zh/drivers/rocketchat) | ✅ | ✅ | Outgoing webhook 接收；REST API 或 incoming webhook 发送 |
| Webhook | [Webhook](/zh/drivers/webhook) | ❌ | ✅ | 仅发送的通用 HTTP webhook |

## 驱动器工作原理

每个驱动器在启动时会：

1. 向桥接引擎**注册发送器**，使桥接引擎能够调用它来投递消息。
2. **监听**平台的消息（WebSocket、长轮询或 HTTP Webhook）。
3. 将每条收到的消息**规范化**为 `NormalizedMessage`，并传递给桥接引擎。
4. 当桥接引擎调用其发送器时，**发送**格式化后的文本和附件。

## 媒体文件处理

所有驱动器共享同一套媒体下载工具。当一条带附件的消息到达时，桥接引擎会将附件列表传递给目标驱动器的 `send()` 方法。各驱动器按照 `max_file_size` 配置的上限下载文件，并通过目标平台的原生 API 重新上传。

若文件超过大小限制或下载失败，则将文字回退内容附加到消息末尾：

```
[Image: photo.jpg](https://example.com/photo.jpg)
```
