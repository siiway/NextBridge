> This document was written by AI and has been manually reviewed.

# Platform Support Status

| Platform | Status | Receive | Send | Mentions | Replies | Media | Custom Proxy | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Tencent QQ** (via NapCat) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | Uses unofficial NapCat WebSocket bridge |
| **Discord** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | Receive via bot gateway; send via webhook or bot |
| **Telegram** | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ✅ | ⚠️ | Uses long polling |
| **Feishu / Lark** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | Webhook receive; IM API send; **SDK doesn't support proxy** |
| **DingTalk** | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ✅ | ❌ | Webhook receive; Robot API send; **SDK doesn't support proxy** |
| **Yunhu** | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | Webhook receive; open API send; **native mentions not yet supported** |
| **KOOK** | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ✅ | ⚠️ | WebSocket receive; bot API send; uploads to KOOK CDN |
| **VoceChat** | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ✅ | ⚠️ | |
| **Matrix** | ⚠️ | ✅ | ✅ | ⚠️ | ⚠️ | ✅ | ⚠️ | Client sync loop; no E2E encryption support yet |
| **Signal** | ⚠️ | ✅ | ✅ | ⚠️ | ⚠️ | ✅ | ⚠️ | Requires signal-cli REST API |
| **Microsoft Teams** | ⚠️ | ✅ | ✅ | ⚠️ | ⚠️ | ✅ | ⚠️ | Bot Framework connector |
| **Google Chat** | ⚠️ | ✅ | ✅ | ⚠️ | ⚠️ | ✅ | ⚠️ | REST API with service account |
| **Slack** | ⚠️ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ⚠️ | Socket Mode or Events API receive; bot or webhook send |
| **Mattermost** | ⚠️ | ✅ | ✅ | ⚠️ | ⚠️ | ✅ | ⚠️ | WebSocket receive; REST API send |
| **Rocket.Chat** | ⚠️ | ✅ | ✅ | ⚠️ | ⚠️ | ✅ | ⚠️ | Outgoing webhook receive; REST API or incoming webhook send |
| **Webhook** | ⚠️ | ❌ | ✅ | - | - | ⚠️ | ⚠️ | Send-only generic HTTP webhook |
| **WhatsApp** | ⏸️ | - | - | - | - | - | - | No public bot API or stable community libraries |
| **WeChat** | ⏸️ | - | - | - | - | - | - | High risk of account ban |
| **Tailchat** | ❌ | - | - | - | - | - | - | Planned |
| **Zulip** | ❌ | - | - | - | - | - | - | Planned |
| **LINE** | ❌ | - | - | - | - | - | - | Planned |
| **Viber** | ❌ | - | - | - | - | - | - | Planned |

## Legend
- ✅ **Supported**: Fully implemented and verified.
- ⚠️ **Supported (Not Tested)**: Implemented and basically tested but requires further testing to ensure stability.
- ⏸️ **Paused**: Development suspended due to technical or policy limitations.
- ❌ **Not Supported**: Not yet implemented.
