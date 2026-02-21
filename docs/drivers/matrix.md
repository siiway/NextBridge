# Matrix

The Matrix driver receives messages via a long-poll sync loop (using [mautrix-python](https://github.com/mautrix/python)) and sends messages to rooms using the Matrix Client-Server API.

## Setup

1. Create a Matrix account for the bot on your homeserver (or any compatible homeserver such as matrix.org).
2. Note the full user ID (e.g. `@mybot:matrix.org`) and homeserver URL (e.g. `https://matrix.org`).
3. Either use the password directly, or log in once to obtain an access token and use that.
4. Invite the bot account to each room it should bridge.

## Config keys

Add under `matrix.<instance_id>` in your config file:

| Key | Required | Default | Description |
|---|---|---|---|
| `homeserver` | Yes | — | Homeserver URL, e.g. `https://matrix.org` |
| `user_id` | Yes | — | Full Matrix user ID, e.g. `@mybot:matrix.org` |
| `password` | No* | — | Login password |
| `access_token` | No* | — | Access token (alternative to `password`) |
| `max_file_size` | No | `52428800` (50 MB) | Maximum bytes per attachment when sending |

\* Either `password` or `access_token` must be provided.

```json
{
  "matrix": {
    "mx_main": {
      "homeserver": "https://matrix.org",
      "user_id": "@mybot:matrix.org",
      "password": "your_password",
      "max_file_size": 52428800
    }
  }
}
```

## Rule channel keys

Use under `channels` or `from`/`to` in `rules.json`:

| Key | Description |
|---|---|
| `room_id` | Matrix room ID, e.g. `!abc123:matrix.org` |

```json
{
  "mx_main": {
    "room_id": "!abc123:matrix.org"
  }
}
```

## Notes

- The bot ignores its own messages to prevent echo loops.
- Media received from Matrix is downloaded via the authenticated client before being forwarded, so downstream platforms do not need Matrix credentials.
- Outgoing media is uploaded to the homeserver via the Matrix media API and sent as native Matrix media events (`m.image`, `m.video`, `m.audio`, `m.file`).
- Historical messages from before the bot connected are skipped automatically on startup.
- E2E encryption is not currently supported.
