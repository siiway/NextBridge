# Mattermost

The Mattermost driver connects to your self-hosted or cloud Mattermost server using the **WebSocket API** for real-time receive and the **REST API** for sending. No extra dependencies are needed beyond what NextBridge already uses.

## Setup

### 1. Create a Bot Account (recommended)

1. Log in as a system admin and go to **System Console → Integrations → Bot Accounts**.
2. Enable bot accounts, then click **Add Bot Account**.
3. Fill in a username, display name, and description; click **Create Bot Account**.
4. Copy the generated **token** — this is your `token` config value.
5. Invite the bot to every channel it should bridge (click the channel name → **Add Members**).

### 2. Personal Access Token (alternative)

If bot accounts are unavailable:

1. In your Mattermost profile, go to **Security → Personal Access Tokens**.
2. Click **Create Token**, give it a name, and copy the token.
3. Ensure **Personal Access Tokens** are enabled in **System Console → Integrations**.

## Config keys

Add under `mattermost.<instance_id>` in your config file:

| Key | Required | Default | Description |
|---|---|---|---|
| `server_url` | Yes | — | Base URL of the Mattermost server, e.g. `"https://mattermost.example.com"` |
| `token` | Yes | — | Bot token or personal access token |
| `max_file_size` | No | `52428800` (50 MB) | Maximum attachment size in bytes |

```json
{
  "mattermost": {
    "mm_main": {
      "server_url": "https://mattermost.example.com",
      "token": "your-bot-or-personal-access-token"
    }
  }
}
```

## Rule channel keys

| Key | Description |
|---|---|
| `channel_id` | Mattermost channel ID |

To find a channel ID: open the channel, click the channel name at the top, and look for the ID in the URL (`/team-name/channels/channel-name` → copy the channel ID from the API or use `/api/v4/channels/name/{team}/{channel}`). The easiest method is to inspect any message in the channel via the Mattermost REST API.

```json
{
  "mm_main": {
    "channel_id": "abc123def456"
  }
}
```

## How it works

**Receive:** At startup, the driver fetches the bot's own user ID (`/api/v4/users/me`) so it can filter out its own messages. It then connects to the Mattermost WebSocket endpoint (`/api/v4/websocket`) and sends an authentication challenge with the token. On every `posted` event:
- System posts (joins, leaves, header changes) are ignored by checking the post `type` field
- File attachments are fetched from `/api/v4/files/{id}` using the same token and forwarded as binary data

The WebSocket reconnects automatically after 5 seconds if the connection drops.

**Send:** For each outgoing message the driver:
1. Uploads any binary attachments to `/api/v4/files` (multipart) and collects the returned `file_id` values
2. Creates a post via `POST /api/v4/posts` with `message` and `file_ids`
3. Attachments that cannot be fetched are appended as text labels (`[Type: filename]`)

## Notes

- The bot account must be **invited to each channel** it should read and write. Messages in channels the bot isn't a member of are not delivered over the WebSocket.
- Mattermost uses standard Markdown for formatting. The `rich_header` prefix renders as `**Title** · *Content*`.
- Display name resolution priority: **Nickname** → **First + Last name** → **Username**.
- No new Python packages are required — the driver uses only `aiohttp`, which NextBridge already depends on.
- User avatars are served at `/api/v4/users/{user_id}/image` and require a valid session to view; downstream platforms that hotlink avatars may see an error if the Mattermost server is not publicly accessible.
