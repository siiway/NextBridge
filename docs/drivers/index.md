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
