# Microsoft Teams

The Teams driver bridges Microsoft Teams with the rest of your platforms using the **Azure Bot Framework**. It runs an HTTP server that Teams calls for incoming messages and uses the **Bot Connector REST API** to send replies.

## Prerequisites

1. **Create an Azure Bot resource** in the [Azure portal](https://portal.azure.com/).
2. On the bot resource, note the **Application (client) ID** and create a **client secret** under *Certificates & secrets*.
3. Under *Channels*, add the **Microsoft Teams** channel.
4. Set the bot's **Messaging endpoint** to `https://<your-host>:<listen_port><listen_path>`.
   The endpoint must be publicly reachable over HTTPS (use a reverse proxy such as nginx or a tunnel like ngrok for development).

## Config keys

Add under `teams.<instance_id>` in `config.json`:

| Key | Required | Default | Description |
|---|---|---|---|
| `app_id` | Yes | — | Azure bot Application (client) ID |
| `app_secret` | Yes | — | Azure bot client secret |
| `listen_port` | No | `3978` | Port the driver listens on for incoming activities |
| `listen_path` | No | `"/api/messages"` | HTTP path for the messaging endpoint |
| `max_file_size` | No | `20971520` | Max attachment size in bytes (default 20 MB) |

```json
{
  "teams": {
    "my_teams": {
      "app_id":     "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "app_secret": "your-client-secret"
    }
  }
}
```

## Rule channel keys

| Key | Description |
|---|---|
| `service_url` | Bot Framework service URL from the incoming activity (e.g. `"https://smba.trafficmanager.net/amer/"`) |
| `conversation_id` | Teams conversation ID from the incoming activity |

Both values are automatically present in every message the driver receives. Copy them from logs or use a webhook capture tool to discover them for the first message.

```json
{
  "teams": {
    "my_teams": {
      "service_url":     "https://smba.trafficmanager.net/amer/",
      "conversation_id": "19:abc123@thread.tacv2"
    }
  }
}
```

## How it works

**Receive:** The driver starts an aiohttp HTTP server. When a user sends a message in Teams, the Bot Framework POSTs a JSON *Activity* to the endpoint. The driver:
- Ignores non-message events (typing indicators, reactions, etc.)
- Strips @-mention text of the bot from the message body
- Skips messages sent by the bot itself (identified by the `28:` id prefix)
- Forwards the normalized message to the bridge

**Send:** For each outgoing message the driver:
1. Fetches an OAuth2 client-credentials token from Microsoft identity (cached and auto-refreshed)
2. POSTs a `message` activity to `{service_url}/v3/conversations/{conversation_id}/activities`
3. For images, sends an Adaptive Card with the image embedded as base64
4. For other file types, sends a text label `[Type: filename]` (Teams file uploads require SharePoint integration not available via the REST API alone)

## Notes

- The messaging endpoint **must be HTTPS** in production; Teams rejects plain HTTP endpoints.
- `service_url` varies by tenant region. Use the value reported in the first incoming activity for that conversation.
- The `rich_header` prefix is rendered using Markdown bold/italic (`**Title** · *Content*`).
- Teams has a ~28 KB limit on Adaptive Card payloads. Large images are sent as text labels when the base64-encoded size would exceed this.
