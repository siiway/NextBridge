# Feishu / Lark

The Feishu driver supports two receive modes and sends via the Feishu IM v1 API using [lark-oapi](https://github.com/larksuite/oapi-sdk-python).

Feishu (China) and Lark (international) use the same API and the same driver.

## Receive modes

### HTTP webhook (default)

Feishu pushes events to an HTTP endpoint you expose. The driver starts an aiohttp server on a configurable port.

**Setup**

1. Go to the [Feishu Open Platform](https://open.feishu.cn) (or [Lark Developer](https://open.larksuite.com)).
2. Create a **custom app** and enable the **im:message:receive_v1** event.
3. Under **Event Subscriptions**, set the request URL to `http://your-host:8080/event` (matching your `listen_port` and `listen_path`).
4. Copy the **App ID**, **App Secret**, **Verification Token**, and **Encrypt Key** (leave encrypt key blank to disable encryption).
5. Add the bot to the target group chat.

::: warning Public endpoint required
Feishu must be able to reach your HTTP endpoint from the internet. Use a reverse proxy, tunnel (e.g. ngrok), or deploy on a public server.
:::

### Long connection / WebSocket

The driver establishes a persistent outbound WebSocket connection to Feishu's servers. No public HTTP endpoint is required — useful for local or firewalled deployments.

**Setup**

1. Go to the [Feishu Open Platform](https://open.feishu.cn) (or [Lark Developer](https://open.larksuite.com)).
2. Create a **custom app** and enable the **im:message:receive_v1** event.
3. Under **Event Subscriptions**, select **"Use long connection to receive events"** instead of setting a request URL.
4. Copy the **App ID** and **App Secret**.
5. Add the bot to the target group chat.
6. Set `use_long_connection: true` in your config.

## Config keys

Add under `feishu.<instance_id>` in `config.json`:

| Key | Required | Default | Description |
|---|---|---|---|
| `app_id` | Yes | — | Feishu/Lark App ID |
| `app_secret` | Yes | — | Feishu/Lark App Secret |
| `use_long_connection` | No | `false` | `true` = WebSocket long connection; `false` = HTTP webhook |
| `verification_token` | No | `""` | Event verification token — HTTP webhook mode only |
| `encrypt_key` | No | `""` | Event encryption key — HTTP webhook mode only (leave empty to disable) |
| `listen_port` | No | `8080` | HTTP port to listen on — HTTP webhook mode only |
| `listen_path` | No | `"/event"` | HTTP path for incoming events — HTTP webhook mode only |

**HTTP webhook example**

```json
{
  "feishu": {
    "fs_main": {
      "app_id": "cli_xxxxxxxxxxxx",
      "app_secret": "your_app_secret",
      "verification_token": "your_verification_token",
      "encrypt_key": "",
      "listen_port": 8080,
      "listen_path": "/event"
    }
  }
}
```

**Long connection example**

```json
{
  "feishu": {
    "fs_main": {
      "app_id": "cli_xxxxxxxxxxxx",
      "app_secret": "your_app_secret",
      "use_long_connection": true
    }
  }
}
```

## Rule channel keys

Use under `channels` or `from`/`to` in `rules.json`:

| Key | Description |
|---|---|
| `chat_id` | Feishu open chat ID, e.g. `"oc_xxxxxxxxxxxxxxxxxx"` |

```json
{
  "fs_main": { "chat_id": "oc_xxxxxxxxxxxxxxxxxx" }
}
```

You can find the chat ID in the Feishu developer console, or from the event payload of any message sent to the bot in that chat.

## Notes

- Currently only **text messages** are received. Other message types (cards, files, stickers) are ignored on the receive side.
- Outgoing attachments are sent as URLs appended to the message text (Feishu file upload via the API requires additional permissions).
- The sender's display name is shown as their `open_id`. Resolving the human-readable name requires an extra user-info API call and is not currently implemented.
