> This document was written by AI and has been manually reviewed.

# Platform Support Status

Note: `Receive` means messages can be ingested into NextBridge; `Send` means NextBridge can send messages to that platform.

| Platform                    | Status | Receive | Send | Mentions | Replies | Media | Custom Proxy | Notes                                                                   |
| :-------------------------- | :----- | :------ | :--- | :------- | :------ | :---- | :----------- | :---------------------------------------------------------------------- |
| **Tencent QQ** (via NapCat) | ✅      | ✅       | ✅    | ✅        | ✅       | ✅     | ✅            | Uses unofficial NapCat WebSocket bridge                                 |
| **Discord**                 | ✅      | ✅       | ✅    | ✅        | ℹ️      | ✅     | ✅            | Webhook cannot specify reply target; reply bridging requires bot path   |
| **Telegram**                | ✅      | ✅       | ✅    | ✅        | ✅       | ⚠️    | ✅            | Uses long polling                                                       |
| **Feishu / Lark**           | ✅      | ✅       | ✅    | ⚠️       | ⚠️      | ❌     | ❌            | Webhook / WebSocket receive; IM API send; **SDK doesn't support proxy** |
| **DingTalk**                | ✅      | ✅       | ✅    | ⚠️       | ⚠️      | ✅     | ❌            | Webhook receive; Robot API send; **SDK doesn't support proxy**          |
| **Yunhu**                   | ✅      | ✅       | ✅    | ❌        | ⚠️      | ℹ️     | ✅            | Webhook receive; open API send; **file receive is unavailable, file send works**; **native mentions not yet supported** |
| **KOOK**                    | ✅      | ✅       | ✅    | ⚠️       | ⚠️      | ✅     | ⚠️           | WebSocket receive; bot API send; uploads to KOOK CDN                    |
| **VoceChat**                | ✅      | ✅       | ✅    | ⚠️       | ⚠️      | ✅     | ⚠️           |                                                                         |
| **Matrix**                  | ✅      | ✅       | ✅    | ⚠️       | ⚠️      | ⚠️    | ⚠️           | E2E encryption supported when `enable_e2e` is enabled                   |
| **Signal**                  | ⚠️     | ✅       | ✅    | ⚠️       | ⚠️      | ✅     | ⚠️           | Requires signal-cli REST API                                            |
| **Microsoft Teams**         | ⚠️     | ✅       | ✅    | ⚠️       | ⚠️      | ✅     | ⚠️           | Bot Framework connector                                                 |
| **Google Chat**             | ⚠️     | ✅       | ✅    | ⚠️       | ⚠️      | ✅     | ⚠️           | REST API with service account                                           |
| **Slack**                   | ⚠️     | ✅       | ✅    | ✅        | ⚠️      | ✅     | ⚠️           | Socket Mode or Events API receive; bot or webhook send                  |
| **Mattermost**              | ⚠️     | ✅       | ✅    | ⚠️       | ⚠️      | ✅     | ⚠️           | WebSocket receive; REST API send                                        |
| **Rocket.Chat**             | ⚠️     | ✅       | ✅    | ⚠️       | ⚠️      | ✅     | ⚠️           | Outgoing webhook receive; REST API or incoming webhook send             |
| **Webhook**                 | ⚠️     | ❌       | ✅    | -        | -       | ⚠️    | ⚠️           | Send-only generic HTTP webhook                                          |
| **WhatsApp**                | ⚠️     | ⚠️      | ⚠️   | ❌        | ❌       | ⚠️    | ❌            | Uses neonize (go-whatsapp); media received as text fallback             |
| **WeChat**                  | ⏸️     | -       | -    | -        | -       | -     | -            | High risk of account ban                                                |
| **Tailchat**                | ❌      | -       | -    | -        | -       | -     | -            | Planned                                                                 |
| **Zulip**                   | ❌      | -       | -    | -        | -       | -     | -            | Planned                                                                 |
| **LINE**                    | ❌      | -       | -    | -        | -       | -     | -            | Planned                                                                 |
| **Viber**                   | ❌      | -       | -    | -        | -       | -     | -            | Planned                                                                 |

## Legend
- ✅ **Supported**: Implemented and verified.
- ⚠️ **Supported (Not Tested)**: Implemented and basically tested but requires further testing to ensure stability.
- ℹ️ **Supported (Limited)**: Supported, but has known platform/API limitations. See the corresponding driver documentation for details.
- ⏸️ **Paused**: Development suspended due to technical or policy limitations.
- ❌ **Not Supported**: Not yet implemented.
