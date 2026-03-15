> This document was written by AI and has been manually reviewed.

# Drivers Overview

A **driver** is the adapter between NextBridge and a specific chat platform. Each driver handles receiving messages from its platform and sending messages to it.

## Supported platforms

| Platform | Driver | Receive | Send | Notes |
|---|---|---|---|---|
| Tencent QQ | [NapCat](/drivers/napcat) | ✅ | ✅ | Uses the unofficial NapCat WebSocket bridge |
| Discord | [Discord](/drivers/discord) | ✅ | ✅ | Receive via bot gateway; send via webhook or bot |
| Telegram | [Telegram](/drivers/telegram) | ✅ | ✅ | Uses long polling |
| Feishu / Lark | [Feishu](/drivers/feishu) | ✅ | ✅ | Webhook receive; IM API send |
| DingTalk | [DingTalk](/drivers/dingtalk) | ✅ | ✅ | Webhook receive; Robot API send |
| Yunhu (云湖) | [Yunhu](/drivers/yunhu) | ✅ | ✅ | Webhook receive; open API send |
| KOOK (开黑啦) | [KOOK](/drivers/kook) | ✅ | ✅ | WebSocket receive; bot API send; uploads to KOOK CDN |
| VoceChat | [VoceChat](/drivers/vocechat) | ✅ | ✅ | |
| Matrix | [Matrix](/drivers/matrix) | ✅ | ✅ | Client sync loop; no E2E encryption support yet |
| Signal | [Signal](/drivers/signal) | ✅ | ✅ | Requires signal-cli REST API |
| Microsoft Teams | [Teams](/drivers/teams) | ✅ | ✅ | Bot Framework connector |
| Google Chat | [Google Chat](/drivers/googlechat) | ✅ | ✅ | REST API with service account |
| Slack | [Slack](/drivers/slack) | ✅ | ✅ | Socket Mode or Events API receive; bot or webhook send |
| Mattermost | [Mattermost](/drivers/mattermost) | ✅ | ✅ | WebSocket receive; REST API send |
| Rocket.Chat | [Rocket.Chat](/drivers/rocketchat) | ✅ | ✅ | Outgoing webhook receive; REST API or incoming webhook send |
| Webhook | [Webhook](/drivers/webhook) | ❌ | ✅ | Send-only generic HTTP webhook |

## How drivers work

Every driver:

1. **Registers a sender** with the bridge on startup so the bridge can call it to deliver messages.
2. **Listens** for incoming messages (WebSocket, long-polling, or HTTP webhook).
3. **Normalizes** each incoming message into a `NormalizedMessage` and passes it to the bridge.
4. **Sends** formatted text and attachments when the bridge calls its sender.

## Media handling

All drivers share a common media-download utility. When a message with attachments arrives, the bridge passes the attachment list to the target driver's `send()` method. Each driver downloads the file (up to `max_file_size` bytes) and re-uploads it using the target platform's native API.

If a file exceeds the size limit or the download fails, a text fallback is appended to the message:

```
[Image: photo.jpg](https://example.com/photo.jpg)
```
