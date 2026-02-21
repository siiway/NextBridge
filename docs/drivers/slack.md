# Slack

The Slack driver supports two independent receive modes and two independent send modes. Mix and match to suit your setup.

## Receive modes

| Mode | Requires | Description |
|---|---|---|
| **Socket Mode** | `app_token` | NextBridge opens a WebSocket to Slack. No public URL needed. |
| **Events API** | `signing_secret` + `listen_port` | Slack POSTs events to your HTTP endpoint. Requires a public URL. |

If `app_token` is set, Socket Mode is used and Events API config is ignored.

## Send modes

| Mode | Config key | Description |
|---|---|---|
| **Bot** (default) | `send_method: "bot"` | Sends via `chat.postMessage`. Supports file uploads and per-message identity. |
| **Incoming Webhook** | `send_method: "webhook"` | POSTs to a fixed Incoming Webhook URL. Text-only; `channel_id` is ignored. |

### Per-message identity (username and avatar)

The rule `msg` config keys `webhook_title` and `webhook_avatar` control the sender name and avatar displayed in Slack. How they are applied depends on the send mode and available config:

| Condition | Behaviour |
|---|---|
| `send_method: "bot"` | `chat.postMessage` is called with `username` and `icon_url`. Requires the `chat:write.customize` scope. |
| `send_method: "webhook"` + `bot_token` set | Automatically falls back to `chat.postMessage` (with identity) whenever `webhook_title` or `webhook_avatar` is present. Also requires `chat:write.customize`. |
| `send_method: "webhook"` + no `bot_token` | Identity fields are ignored — Slack Incoming Webhooks do not support per-message username or icon overrides. |

To enable per-message identity, add `chat:write.customize` to your bot's OAuth scopes in the Slack app settings.

---

## Socket Mode setup

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and create a new app (from scratch).
2. Under **Socket Mode**, enable Socket Mode and generate an **App-level token** with the `connections:write` scope. This token starts with `xapp-`.
3. Under **OAuth & Permissions**, add these bot token scopes:
   - `channels:history`, `groups:history` — read messages
   - `chat:write` — send messages
   - `chat:write.customize` — per-message username and avatar override (optional)
   - `files:read` — download received files
   - `files:write` — upload files
   - `users:read` — resolve display names
4. Under **Event Subscriptions**, enable events and subscribe to:
   - `message.channels` — public channel messages
   - `message.groups` — private channel messages
5. Install the app to your workspace. Copy the **Bot User OAuth Token** (`xoxb-...`).
6. Invite the bot to each channel it should bridge (`/invite @YourBot`).

## Events API setup

1. Create a Slack app at [api.slack.com/apps](https://api.slack.com/apps).
2. Under **OAuth & Permissions**, add the same bot token scopes listed above (including `chat:write.customize` if you want per-message identity).
3. Under **Event Subscriptions**, enable events and set the **Request URL** to your public endpoint (e.g. `https://example.com/slack/events`).
4. Subscribe to `message.channels` and `message.groups` bot events.
5. Under **Basic Information**, copy the **Signing Secret** (used to verify incoming requests).
6. Install the app and copy the bot token.

## Incoming Webhook setup (send only)

1. In your Slack app, go to **Incoming Webhooks** and activate them.
2. Click **Add New Webhook to Workspace**, choose a channel, and copy the webhook URL.

---

## Config keys

Add under `slack.<instance_id>` in your config file:

| Key | Required | Default | Description |
|---|---|---|---|
| `bot_token` | For bot send / file downloads | — | Bot User OAuth Token, starts with `xoxb-` |
| `app_token` | For Socket Mode receive | — | App-level token, starts with `xapp-` |
| `send_method` | No | `"bot"` | `"bot"` or `"webhook"` |
| `incoming_webhook_url` | For webhook send | — | Slack Incoming Webhook URL |
| `signing_secret` | For Events API receive | — | Slack signing secret for request verification |
| `listen_port` | For Events API receive | — | HTTP port to listen on |
| `listen_path` | No | `"/slack/events"` | HTTP path for the Events API endpoint |
| `max_file_size` | No | `52428800` (50 MB) | Maximum bytes per attachment when sending |

### Socket Mode + Bot send (no public URL)

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

### Events API receive + Incoming Webhook send

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

### Events API receive + Bot send

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

### Incoming Webhook send only (no receive)

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

## Rule channel keys

| Key | Description |
|---|---|
| `channel_id` | Slack channel ID, e.g. `C1234567890` |

The easiest way to find a channel's ID: open the channel in Slack, click the channel name at the top, and copy the ID shown at the bottom of the popup.

> **Note:** `channel_id` is only used for **receive-side routing** and **bot send**. When `send_method` is `"webhook"`, the destination channel is fixed by the webhook URL and `channel_id` is ignored.

```json
{
  "sl_main": {
    "channel_id": "C1234567890"
  }
}
```

## Notes

- Bot messages and system messages (joins, edits, etc.) are ignored to prevent echo loops.
- File downloads require `bot_token` regardless of receive mode.
- When `send_method` is `"webhook"`, messages that contain attachments **or** a custom identity (`webhook_title`/`webhook_avatar`) automatically fall back to `chat.postMessage` if `bot_token` is configured. Without a bot token, attachments become text labels and identity fields are ignored.
- Display names are resolved via the Users API (`bot_token` required) and cached for the lifetime of the process.
- Events API requests older than 5 minutes are rejected to prevent replay attacks.
