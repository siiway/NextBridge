# Signal

The Signal driver connects to a running [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) instance, which handles the Signal protocol on your behalf. The driver receives messages via WebSocket and sends messages via HTTP.

## Prerequisites

You need a running `signal-cli-rest-api` instance. The easiest way is Docker:

```bash
docker run -d \
  --name signal-api \
  -p 8080:8080 \
  -v /path/to/signal-cli-config:/home/.local/share/signal-cli \
  bbernhard/signal-cli-rest-api
```

Then register or link your Signal account via the API's `/v1/register` or `/v1/qrcodelink` endpoints. Refer to the [signal-cli-rest-api documentation](https://bbernhard.github.io/signal-cli-rest-api/) for setup details.

## Config keys

Add under `signal.<instance_id>` in your config file:

| Key | Required | Default | Description |
|---|---|---|---|
| `api_url` | Yes | — | Base URL of your signal-cli-rest-api instance, e.g. `http://localhost:8080` |
| `number` | Yes | — | Your registered Signal phone number, e.g. `+12025551234` |
| `max_file_size` | No | `52428800` (50 MB) | Maximum bytes per attachment when sending |

```json
{
  "signal": {
    "sg_main": {
      "api_url": "http://localhost:8080",
      "number": "+12025551234"
    }
  }
}
```

## Rule channel keys

Use under `channels` or `from`/`to` in `rules.json`:

| Key | Description |
|---|---|
| `recipient` | Phone number for 1-on-1 chats (e.g. `+12025551234`) or `group.<base64id>` for group chats |

```json
{
  "sg_main": {
    "recipient": "+12025551234"
  }
}
```

For group chats, the `recipient` value starts with `group.` followed by the base64-encoded group ID. The easiest way to find it is to send a message to the group and check the incoming envelope logged by NextBridge.

## Notes

- The bot ignores its own messages to prevent echo loops (send-only path, no echo from the WebSocket).
- Received attachments are downloaded from the signal-cli REST API immediately on arrival so downstream platforms can re-upload them without needing access to your Signal instance.
- Outgoing attachments are base64-encoded and sent inline via the `/v2/send` endpoint.
- The driver reconnects automatically with a 5-second backoff if the WebSocket connection drops.
