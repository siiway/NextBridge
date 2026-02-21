# Google Chat

The Google Chat driver bridges Google Chat spaces with the rest of your platforms using a **service account** and the **Google Chat REST API**. It starts an HTTP server that receives message events pushed by Google, and sends replies via the Chat API.

## Prerequisites

::: tip
**Google Workspace** account needed, or you will hit this:
![Google Chat API is only available to Google Workspace users](https://images.krnl64.win/api/get/6efb709e-7dd7-4183-9e25-225004f5695e.png)
:::

1. **Create a Google Cloud project** at [console.cloud.google.com](https://console.cloud.google.com/) (or use an existing one).
2. **Enable the Google Chat API**: go to *APIs & Services → Library*, search for "Google Chat API", and enable it.
3. **Create a service account**: go to *IAM & Admin → Service Accounts*, create a new account, and download a JSON key file.
4. **Configure the Chat app**: go to *APIs & Services → Google Chat API → Configuration* and fill in:
   - **App name**, **Avatar URL**, **Description** (required fields)
   - Under **Connection settings**, select **HTTP endpoint URL** and enter your bot's public URL, e.g. `https://example.com/google-chat/events`.
   - Under **Visibility**, choose which users or groups can install the bot.
5. **Add the bot to a space**: In Google Chat, create or open a space, click *Add people & apps*, and add your bot by name.

> The HTTP endpoint must be publicly reachable over HTTPS. Use a reverse proxy (nginx, Caddy) or a tunnel (ngrok) for development.

## Config keys

Add under `googlechat.<instance_id>` in `config.json`:

| Key | Required | Default | Description |
|---|---|---|---|
| `service_account_file` | Yes* | — | Path to the service account JSON key file |
| `service_account_json` | Yes* | — | Inline service account JSON string (alternative to file) |
| `listen_port` | No | `8090` | HTTP port the driver listens on |
| `listen_path` | No | `"/google-chat/events"` | HTTP path for the event endpoint |
| `endpoint_url` | No | — | Full public URL of the endpoint (enables request signature verification) |
| `max_file_size` | No | `52428800` (50 MB) | Maximum attachment size in bytes |

\* Exactly one of `service_account_file` or `service_account_json` is required.

### Using a file path

```json
{
  "googlechat": {
    "my_space": {
      "service_account_file": "/secrets/google-chat-sa.json",
      "listen_port": 8090,
      "endpoint_url": "https://example.com/google-chat/events"
    }
  }
}
```

### Inline JSON (useful with secrets managers)

```json
{
  "googlechat": {
    "my_space": {
      "service_account_json": "{\"type\":\"service_account\",\"project_id\":\"...\", ...}"
    }
  }
}
```

## Rule channel keys

| Key | Description |
|---|---|
| `space_name` | Google Chat space resource name, e.g. `"spaces/AAAA"` |

The `space_name` is present in every received event. You can also find it via the Chat API or by inspecting the `name` field of a space object in the Google Cloud Console.

```json
{
  "my_space": {
    "space_name": "spaces/AAAAAbCdEfG"
  }
}
```

## How it works

**Receive:** Google Chat POSTs a JSON event to the configured endpoint whenever a user sends a message to the bot. The driver:
- Returns `{"text": ""}` immediately to acknowledge the event (required by Google)
- Ignores non-`MESSAGE` event types (`ADDED_TO_SPACE`, `REMOVED_FROM_SPACE`, etc.)
- Skips messages sent by bots (including itself)
- Uses `argumentText` (text after the @mention) when available, falling back to the full `text` field
- Downloads inline attachments using the service-account token and forwards them to the bridge

**Send:** For each outgoing message the driver:
1. Obtains (or refreshes) a service-account OAuth2 access token
2. POSTs a `message` to `https://chat.googleapis.com/v1/{space_name}/messages`
3. For images that have a public HTTPS URL, sends a Card v2 with an image widget
4. For other attachments (or images without a public URL), sends a text label `[Type: filename]`

## Request verification

When `endpoint_url` is set, the driver verifies every incoming request against Google's signed OIDC token:
- Checks the `Authorization: Bearer <token>` header
- Validates the token's signature against Google's public keys
- Confirms the audience matches `endpoint_url`
- Confirms the sender email is `chat@system.gserviceaccount.com`

If `endpoint_url` is omitted, verification is skipped (safe for development or deployments behind a firewall).

## Notes

- The service account must have the **Chat API** enabled in the same project; it does **not** need any IAM roles.
- Google Chat requires a valid HTTPS endpoint. Plain HTTP is rejected by the Chat configuration UI.
- Images are sent as Card v2 widgets only when the attachment already has a public URL. Binary attachments from other platforms (e.g., NapCat) appear as text labels since Google Chat's REST API does not support direct binary uploads without additional Drive/storage setup.
- The `rich_header` prefix uses Google Chat's limited Markdown syntax: `*bold*` and `_italic_`.
- Google Chat currently supports spaces, direct messages, and group DMs. Use the `space_name` from the appropriate conversation.
