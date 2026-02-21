# Rocket.Chat

The Rocket.Chat driver connects to your self-hosted Rocket.Chat server using an **Outgoing Webhook** for receiving messages and the **REST API** for sending. No extra Python packages are needed.

## Setup

### 1. Create a Bot Account

1. Log in as an admin and go to **Administration → Users → New User**.
2. Fill in the username, name, and email. Under **Roles**, add **bot**.
3. Set a password and save.
4. In your admin profile, go to **Administration → Personal Access Tokens**, create a token for the bot user, and copy both the **token** and the **user ID** (found in **Administration → Users → (bot user) → _id**).

### 2. Configure an Outgoing Webhook

1. Go to **Administration → Integrations → New Integration → Outgoing WebHook**.
2. Set:
   - **Event Trigger**: Message Sent
   - **Enabled**: Yes
   - **Channel**: leave blank to catch all channels, or enter `#channel-name` to limit scope
   - **URLs**: `http(s)://<your-host>:<listen_port><listen_path>`
     e.g. `https://bridge.example.com:8093/rocketchat/webhook`
   - **Token**: generate or type a secret — copy it to `webhook_token` in your config
3. Save the integration.

## Config keys

Add under `rocketchat.<instance_id>` in your config file:

| Key | Required | Default | Description |
|---|---|---|---|
| `server_url` | Yes | — | Base URL of the RC server, e.g. `"https://chat.example.com"` |
| `auth_token` | Yes | — | Personal access token for the bot account |
| `user_id` | Yes | — | Bot account user ID |
| `listen_port` | No | `8093` | HTTP port for the incoming webhook |
| `listen_path` | No | `"/rocketchat/webhook"` | HTTP path for the incoming webhook |
| `webhook_token` | No | `""` | Token from the outgoing webhook — verifies requests are from RC |
| `max_file_size` | No | `52428800` (50 MB) | Maximum attachment size in bytes |

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

## Rule channel keys

| Key | Description |
|---|---|
| `room_id` | Rocket.Chat room ID (alphanumeric string) |

To find a room ID, call the REST API while authenticated:

```
GET /api/v1/channels.info?roomName=general
```

The `_id` field in the response is the `room_id`. For direct messages use `/api/v1/dm.list`.

```json
{
  "rc_main": {
    "room_id": "GENERAL"
  }
}
```

## How it works

**Receive:** Rocket.Chat's Outgoing Webhook posts a JSON payload to your configured URL whenever a message is sent. The driver:
- Verifies the `token` field against `webhook_token` (if set)
- Ignores messages where `user_id` matches the bot's own `user_id`
- Downloads any file attachments using the bot's credentials (RC files require authentication)
- Forwards the normalized message to the bridge

**Send:** For each outgoing message the driver:
1. Sends text via `POST /api/v1/chat.postMessage`
2. Uploads binary attachments via `POST /api/v1/rooms.upload/{room_id}` (multipart) — files display inline in Rocket.Chat
3. Attachments that cannot be fetched are sent as text labels (`[Type: filename]`)

## Per-message username and avatar

Rocket.Chat's `chat.postMessage` API supports `alias` (display name) and `avatar` (avatar image URL) fields that override the bot's identity for individual messages. Configure them in the `msg` block of your rule using the same template variables available in `msg_format`:

```json
{
  "rules": [{
    "from": { "dc": { "channel_id": "123" } },
    "to":   { "rc_main": { "room_id": "GENERAL" } },
    "msg": {
      "msg_format":  "[Discord] {username}: {msg}",
      "rc_alias":    "{username}",
      "rc_avatar":   "{user_avatar}"
    }
  }]
}
```

| Key | Description |
|---|---|
| `rc_alias` | Display name shown on the message (e.g. `"{username}"`) |
| `rc_avatar` | Avatar URL shown on the message (e.g. `"{user_avatar}"`). Must be an HTTPS URL; ignored otherwise. |

The bot must have the **bot** role in Rocket.Chat for these overrides to be accepted.

## Notes

- The bot user must be a **member of every room** it should read and write. Add it via **Room Info → Members → Add**.
- Make sure the webhook URL is reachable from the Rocket.Chat server. If running behind a reverse proxy, ensure the path is forwarded correctly.
- Personal access tokens do not expire by default; if they do, regenerate and update your config.
