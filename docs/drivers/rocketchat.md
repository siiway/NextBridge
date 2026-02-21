# Rocket.Chat

The Rocket.Chat driver receives messages via a **Outgoing Webhook** and supports two sending modes: **API** (REST API with bot credentials — the default) and **Webhook** (Incoming Webhook URL). No extra Python packages are needed.

## Setup

### 1. Create a Bot Account (required for API mode; recommended for webhook mode too)

1. Log in as an admin and go to **Administration → Users → New User**.
2. Fill in the username, name, and email. Under **Roles**, add **bot**.
3. Set a password and save.
4. Go to **Administration → Personal Access Tokens**, create a token for the bot user, and copy both the **token** and the **user ID** (found in **Administration → Users → (bot user) → _id**).

### 2. Configure an Outgoing Webhook (receive)

1. Go to **Administration → Integrations → New Integration → Outgoing WebHook**.
2. Set:
   - **Event Trigger**: Message Sent
   - **Enabled**: Yes
   - **Channel**: leave blank to catch all channels, or enter `#channel-name` to limit scope
   - **URLs**: `http(s)://<your-host>:<listen_port><listen_path>`
     e.g. `https://bridge.example.com:8093/rocketchat/webhook`
   - **Token**: generate or type a secret — copy it to `webhook_token` in your config
3. Save the integration.

### 3a. API send mode — no extra setup needed

The bot account's credentials are used directly.

### 3b. Webhook send mode — create an Incoming Webhook

1. Go to **Administration → Integrations → New Integration → Incoming WebHook**.
2. Set **Enabled** to Yes and choose a default channel (overridden at runtime; pick any).
3. Copy the generated **Webhook URL** — this is your `webhook_url` config value.

## Config keys

Add under `rocketchat.<instance_id>` in your config file:

| Key | Required | Default | Description |
|---|---|---|---|
| `send_method` | No | `"api"` | `"api"` or `"webhook"` |
| `server_url` | Yes (api) | `""` | Base URL, e.g. `"https://chat.example.com"`. Also used to download received attachments. |
| `auth_token` | Yes (api) | `""` | Personal access token for the bot account |
| `user_id` | Yes (api) | `""` | Bot account user ID |
| `webhook_url` | Yes (webhook) | `""` | Incoming Webhook URL for `send_method="webhook"` |
| `listen_port` | No | `8093` | HTTP port for the outgoing webhook listener |
| `listen_path` | No | `"/rocketchat/webhook"` | HTTP path for the outgoing webhook listener |
| `webhook_token` | No | `""` | Token from the outgoing webhook — verifies requests are from RC |
| `max_file_size` | No | `52428800` (50 MB) | Maximum attachment size in bytes |

**API mode example:**

```json
{
  "rocketchat": {
    "rc_main": {
      "server_url": "https://chat.example.com",
      "auth_token": "your-personal-access-token",
      "user_id": "bot-user-id",
      "webhook_token": "your-outgoing-webhook-token"
    }
  }
}
```

**Webhook mode example:**

```json
{
  "rocketchat": {
    "rc_wh": {
      "send_method": "webhook",
      "webhook_url": "https://chat.example.com/hooks/your-incoming-webhook-id/token",
      "webhook_token": "your-outgoing-webhook-token"
    }
  }
}
```

## Rule channel keys

| Key | Required | Description |
|---|---|---|
| `room_id` | API mode only | Rocket.Chat room ID, e.g. `"GENERAL"` |

To find a room ID, call the REST API while authenticated:

```
GET /api/v1/channels.info?roomName=general
```

The `_id` field in the response is the `room_id`. For direct messages use `/api/v1/dm.list`.

In webhook mode the destination channel is determined by the incoming webhook configuration (and can optionally be overridden per-message via the `channel` field — not currently exposed).

```json
{
  "rc_main": { "room_id": "GENERAL" }
}
```

## How it works

**Receive:** Rocket.Chat's Outgoing Webhook posts a JSON payload whenever a message is sent. The driver:
- Verifies the `token` field against `webhook_token` (if set)
- Ignores messages where `user_id` matches the bot's own `user_id` (API mode)
- Downloads file attachments using the bot's credentials when `auth_token` is set
- Forwards the normalized message to the bridge

**Send — API mode:**
1. Sends text via `POST /api/v1/chat.postMessage` with `alias`/`avatar` overrides when configured
2. Uploads binary attachments via `POST /api/v1/rooms.upload/{room_id}` — files display inline
3. Attachments that cannot be fetched are sent as text labels (`[Type: filename]`)

**Send — Webhook mode:**
1. POSTs JSON to the incoming webhook URL with `username`/`icon_url` overrides when configured
2. Attachments with a public URL are included as an `attachments` array (images render inline)
3. Byte-only attachments (no public URL) fall back to text labels — incoming webhooks cannot upload files

## Per-message username and avatar

Both send modes support per-message sender identity. Configure them in the `msg` block of your rule:

```json
{
  "rules": [{
    "from": { "dc": { "channel_id": "123" } },
    "to":   { "rc_main": { "room_id": "GENERAL" } },
    "msg": {
      "msg_format": "[Discord] {username}: {msg}",
      "rc_alias":   "{username}",
      "rc_avatar":  "{user_avatar}"
    }
  }]
}
```

| Key | Description |
|---|---|
| `rc_alias` | Display name shown on the message (e.g. `"{username}"`) |
| `rc_avatar` | Avatar URL shown on the message (e.g. `"{user_avatar}"`). Must be HTTPS; ignored otherwise. |

In API mode the bot must have the **bot** role for `alias`/`avatar` overrides to be accepted.

## Notes

- In API mode, the bot user must be a **member of every room** it should read and write. Add it via **Room Info → Members → Add**.
- In webhook mode there is no `room_id` channel key — the destination is set inside the incoming webhook configuration in Rocket.Chat.
- Make sure the listener URL is reachable from the Rocket.Chat server. If running behind a reverse proxy, ensure the path is forwarded correctly.
- Personal access tokens do not expire by default; regenerate and update your config if they do.
