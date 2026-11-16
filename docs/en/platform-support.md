> This document was written by AI and has been manually reviewed.

# Platform Support Status

| Platform                    | Status | Receive | Send | Mentions | Replies | Media | Custom Proxy | Notes                                                                   |
| :-------------------------- | :----- | :------ | :--- | :------- | :------ | :---- | :----------- | :---------------------------------------------------------------------- |
| **Tencent QQ**                | ✅      | ✅       | ✅    | ✅        | ✅       | ✅     | ✅            | Supports multiple protocol backends: NapCat, Lagrange, OneBot v11; incoming edits simulated via quote + prefix; recalls synced both ways |
| **Discord**                 | ✅      | ✅       | ✅    | ✅        | ℹ️      | ✅     | ✅            | Webhook cannot specify reply target; reply bridging requires bot path; recall detection requires bot   |
| **Telegram**                | ✅      | ✅       | ✅    | ✅        | ✅       | ⚠️    | ✅            | Uses long polling; can apply recalls; Bot API cannot detect local deletions, use `/recall` reply to notify |
| **Feishu / Lark**           | ✅      | ✅       | ✅    | ⚠️       | ⚠️      | ❌     | ❌            | Webhook / WebSocket receive; IM API send; **SDK doesn't support proxy** |
| **DingTalk**                | ✅      | ✅       | ✅    | ⚠️       | ⚠️      | ✅     | ❌            | Webhook receive; Robot API send; **SDK doesn't support proxy**          |
| **Yunhu**                   | ✅      | ✅       | ✅    | ❌        | ⚠️      | ✅     | ✅            | Webhook receive; open API send; **native mentions not yet supported**   |
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
