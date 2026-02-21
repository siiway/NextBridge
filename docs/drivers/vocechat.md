# VoceChat

The VoceChat driver bridges a self-hosted [VoceChat](https://voce.chat/) server with the rest of your platforms. It runs an HTTP webhook endpoint that VoceChat calls for incoming messages, and sends via the **Bot REST API**.

No extra Python packages are needed beyond what NextBridge already uses.

## Setup

### 1. Create a bot and get the API key

1. Log in to VoceChat as an admin and go to **Settings → Bots**.
2. Click **New Bot**, fill in a name and description.
3. Copy the generated **API Key** — this is your `api_key` config value.

### 2. Configure the webhook URL

1. In the bot settings, set the **Webhook URL** to your NextBridge endpoint, e.g.
   `https://example.com/vocechat/webhook`
2. VoceChat will send a GET request to verify the URL returns HTTP 200. NextBridge handles this automatically.

### 3. Add the bot to channels

For each channel the bot should bridge, go to the channel settings in VoceChat, click **Add Bot**, and select your bot.

> The webhook endpoint must be reachable from the VoceChat server. Use a reverse proxy or ngrok for development.

## Config keys

Add under `vocechat.<instance_id>` in your config file:

| Key | Required | Default | Description |
|---|---|---|---|
| `server_url` | Yes | — | Base URL of the VoceChat server, e.g. `"https://chat.example.com"` |
| `api_key` | Yes | — | Bot API key from the bot settings page |
| `listen_port` | No | `8091` | HTTP port the webhook listens on |
| `listen_path` | No | `"/vocechat/webhook"` | HTTP path for the webhook endpoint |
| `max_file_size` | No | `52428800` (50 MB) | Maximum attachment size in bytes |

```json
{
  "vocechat": {
    "vc_main": {
      "server_url": "https://chat.example.com",
      "api_key": "your-bot-api-key",
      "listen_port": 8091
    }
  }
}
```

## Rule channel keys

Exactly one of `gid` or `uid` is required per channel entry:

| Key | Description |
|---|---|
| `gid` | VoceChat group (channel) ID — integer |
| `uid` | VoceChat user ID for direct messages — integer |

The channel ID appears in the URL when you open the channel in VoceChat (`/channel/{gid}`). The user ID is visible in user profile URLs.

```json
{
  "vc_main": {
    "gid": 2
  }
}
```

For direct messages:

```json
{
  "vc_main": {
    "uid": 7910
  }
}
```

## How it works

**Receive:** VoceChat POSTs a JSON event to the webhook endpoint for each new message. The driver:
- Responds immediately with HTTP 200 and dispatches processing in the background
- Handles both `text/plain` and `text/markdown` content types as text
- Downloads `vocechat/file` attachments from `/api/resource/file?path={path}` and forwards the bytes
- Skips edits, deletions, and system events (only `normal` and `reply` types are bridged)
- For direct messages, routes back using the sender's `uid` as the channel

**Send:** For each outgoing message the driver:
- Sends text to `POST /api/bot/send_to_group/{gid}` or `/api/bot/send_to_user/{uid}` with `Content-Type: text/plain` (or `text/markdown` when a rich header is present)
- Uploads binary attachments first via `POST /api/bot/file/upload`, then sends a `vocechat/file` reference message
- Falls back to a text label `[Type: filename]` when upload fails

## Notes

- The `x-api-key` header is used for all outbound API calls.
- Markdown formatting is supported by VoceChat. The `rich_header` prefix uses `**bold**` and `*italic*` and is sent with `Content-Type: text/markdown`.
- Multiple bots can be added to the same channel. The driver will receive events from all users, including other bots — configure VoceChat's bot permissions to restrict this if needed.
- No extra Python packages are required — only `aiohttp` which NextBridge already depends on.
