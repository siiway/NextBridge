> This document was written by AI and has been manually reviewed.

# Telegram

The Telegram driver uses [python-telegram-bot](https://python-telegram-bot.org/) with long polling to receive messages and the Bot API to send.

## Setup

1. Message [@BotFather](https://t.me/BotFather) on Telegram and create a new bot with `/newbot`.
2. Copy the bot token it gives you.
3. Add the bot to your group and give it permission to read messages.
4. Get the group's chat ID (tip: forward a message to [@userinfobot](https://t.me/userinfobot), or use the bot API `/getUpdates` endpoint).

## Config keys

Add under `telegram.<instance_id>` in `config.json`:

| Key                   | Required | Default                           | Description                                                                                                                                                                                                                                |
| --------------------- | -------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `bot_token`           | Yes      | —                                 | Bot token from @BotFather                                                                                                                                                                                                                  |
| `max_file_size`       | No       | `52428800` (50 MB)                | Maximum bytes per attachment when sending                                                                                                                                                                                                  |
| `rich_header_host`    | No       | `"https://richheader.siiway.top"` | Base URL of your Cloudflare rich-header worker (see [Rich Header](#rich-header))                                                                                                                                                           |
| `avatar_proxy_host`   | No       | —                                 | Base URL of your Cloudflare avatar proxy worker (see [Avatar Proxy](#avatar-proxy))                                                                                                                                                        |
| `photo_padding_color` | No       | `"#000000"`                       | Padding color used when Telegram image dimensions are invalid (supports `#RGB`, `#RRGGBB`, `#RRGGBBAA`, `r,g,b[,a]`). Set to `null` to disable padding; over-limit images are downgraded to text labels in the same `[Image: ...]` format. |
| `proxy`               | No       | —                                 | Proxy URL for all Telegram API requests (e.g., `http://proxy.example.com:8080` or `socks5://proxy.example.com:1080`). Set to `null` to explicitly disable proxy for this instance (ignores global proxy setting).                          |

```json
{
  "telegram": {
    "tg_main": {
      "bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
      "max_file_size": 52428800,
      "rich_header_host": "https://richheader.siiway.top",
      "avatar_proxy_host": "https://tg-avatar-proxy.yourname.workers.dev",
      "photo_padding_color": "#000000"
    }
  }
}
```

To disable image padding and fallback to text for over-limit images:

```json
{
  "telegram": {
    "tg_main": {
      "photo_padding_color": null
    }
  }
}
```

## Rule channel keys

Use under `channels` or `from`/`to` in `rules.json`:

| Key       | Description                                                                  |
| --------- | ---------------------------------------------------------------------------- |
| `chat_id` | Telegram chat ID. Use a negative number for groups (e.g. `"-1002206757362"`) |

```json
{
  "tg_main": { "chat_id": "-1002206757362" }
}
```

## Received message types

| Telegram type   | Attachment type |
| --------------- | --------------- |
| Photo           | `image`         |
| Video           | `video`         |
| Voice           | `voice`         |
| Audio           | `voice`         |
| Document        | `file`          |
| Animation (GIF) | `video`         |

Media messages may include a caption, which becomes the message text.

## Sending

| Attachment type | Telegram API method |
| --------------- | ------------------- |
| `image`         | `send_photo`        |
| `voice`         | `send_voice`        |
| `video`         | `send_video`        |
| `file`          | `send_document`     |

The message text is sent as the caption of the first attachment. If there are no attachments (or all fail), it is sent as a plain `send_message`. Text for subsequent attachments is omitted.

If an attachment upload fails (for example, Telegram rejects an image), NextBridge falls back to a text label (such as `[Image: xxx]`) for that attachment and continues sending the remaining attachments instead of failing the whole message.

## Rich Header

When a `msg_format` contains a `<richheader title="..." content="..."/>` tag and `rich_header_host` is configured, NextBridge shows a **small link-preview card** above the message text on Telegram. The card displays the sender's avatar, name (title), and a secondary line (content) — visually compact and distinct from the message body.

This works by serving a tiny HTML page with [Open Graph](https://ogp.me/) meta tags from a Cloudflare Worker. Telegram fetches those tags and renders the result as a `prefer_small_media` link preview shown above the text.

### Cloudflare Worker setup

::: tip Public endpoint
We provide a public endpoint, `https://richheader.siiway.top`. Feel free to use it.
:::

1. Go to the [Cloudflare dashboard](https://dash.cloudflare.com/) → **Workers & Pages** → **Create**.
2. Paste the contents of [`cloudflare/richheader-worker.js`](https://github.com/siiway/NextBridge/blob/main/cloudflare/richheader-worker.js) into the editor and deploy.
3. Copy the worker's URL (e.g. `https://richheader.yourname.workers.dev`).
4. Set `rich_header_host` in your Telegram instance config to that URL.

### msg_format example

```json
{
  "my_tg": {
    "chat_id": "-100987654321",
    "msg": {
      "msg_format": "<richheader title=\"{user}\" content=\"id: {user_id}\"/> {msg}"
    }
  }
}
```

### Fallback behaviour

| Condition                          | Behaviour                                                                     |
| ---------------------------------- | ----------------------------------------------------------------------------- |
| `rich_header_host` is not set      | Bold/italic HTML header prepended to the message text                         |
| Message includes media attachments | Same bold/italic HTML fallback (Telegram captions cannot carry link previews) |

## Avatar Proxy

When `avatar_proxy_host` is configured, NextBridge uses a Cloudflare Worker to proxy Telegram user avatars, avoiding exposure of the bot token in URLs. The worker only serves avatar images (jpeg, png, gif, webp) from paths starting with `photos/` or `profile_photos/`.

### Cloudflare Worker setup

1. Go to the [Cloudflare dashboard](https://dash.cloudflare.com/) → **Workers & Pages** → **Create**.
2. Paste the contents of [`cloudflare/tg-avatar-proxy.js`](https://github.com/siiway/NextBridge/blob/main/cloudflare/tg-avatar-proxy.js) into the editor and deploy.
3. Set the `BOT_TOKEN` environment variable in the worker settings (use the same bot token as your Telegram instance).
4. Copy the worker's URL (e.g. `https://tg-avatar-proxy.yourname.workers.dev`).
5. Set `avatar_proxy_host` in your Telegram instance config to that URL.

### Fallback behaviour

| Condition                      | Behaviour                                |
| ------------------------------ | ---------------------------------------- |
| `avatar_proxy_host` is not set | Avatar URLs are not included in messages |

## Notes

- Telegram bots cannot initiate conversations with users. Make sure the bot is already in the target group before running NextBridge.
- The bot's own messages are not echoed back (Telegram does not send bot message events to the bot itself).
- Telegram command pass-through: NextBridge allows built-in commands (`/ping` and `/<command_prefix> ...`, default `/nb ...`) to enter bridge processing. Other bot commands are ignored by the Telegram driver.
