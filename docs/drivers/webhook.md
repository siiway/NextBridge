# Webhook

The Webhook driver is a **send-only** generic driver. When a message is routed to a webhook instance, NextBridge POSTs a JSON payload to the configured URL. There is no receive side — no incoming events are consumed.

Use this driver to push bridge traffic into any HTTP endpoint: custom bots, n8n/Make/Zapier workflows, logging services, etc.

## Config keys

Add under `webhook.<instance_id>` in `config.json`:

| Key | Required | Default | Description |
|---|---|---|---|
| `url` | Yes | — | HTTP endpoint to send to |
| `method` | No | `"POST"` | HTTP method: `"POST"`, `"PUT"`, or `"PATCH"` |
| `headers` | No | `{}` | Extra request headers (e.g. for authentication) |

```json
{
  "webhook": {
    "my_hook": {
      "url": "https://example.com/bridge-events",
      "headers": {
        "Authorization": "Bearer my-secret-token"
      }
    }
  }
}
```

## Rule channel keys

None. The URL is fixed per instance. Any channel dict from the rule is passed through in the payload but is not used for routing.

```json
{
  "my_hook": {}
}
```

## Payload format

Each message POSTs a JSON body:

```json
{
  "text": "formatted message text",
  "channel": { "...": "rule channel dict" },
  "attachments": [
    { "type": "image", "url": "https://...", "name": "photo.jpg", "size": 12345 }
  ]
}
```

Additional fields from the rule's `msg` config block are merged into the top level. For example, if your rule includes `"webhook_title": "{username}"`, the payload will also contain `"webhook_title": "Alice"`.

To include sender metadata in the payload, add the relevant keys to the rule's `msg` block using format variables:

```json
{
  "msg": {
    "user":       "{username}",
    "user_id":    "{user_id}",
    "platform":   "{platform}",
    "avatar":     "{user_avatar}"
  }
}
```

## Notes

- The `rich_header` tag (if present in the formatted text) is applied as a `[Title · Content]` prefix to `text` and is **not** included as a separate field.
- Attachments carry metadata only (`type`, `url`, `name`, `size`). Raw bytes are never sent — the receiving endpoint should download from `url` if needed.
- HTTP 200, 201, 202, and 204 are all treated as success.
