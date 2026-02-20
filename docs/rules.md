# Rules Reference

Message routing is defined in `data/rules.json`:

```json
{
  "rules": [ ...rule objects... ]
}
```

Rules are evaluated in order for every incoming message. A message can match multiple rules.

---

## Rule types

### connect

Links all listed channels **bidirectionally**. Any message from one channel is forwarded to all others.

```json
{
  "type": "connect",
  "channels": {
    "<instance_id>": { ...channel address... },
    "<instance_id>": { ...channel address... }
  },
  "msg": { ...global msg config... }
}
```

#### Per-channel msg override

Each channel entry may contain a `"msg"` key that overrides the global `"msg"` for messages sent **to** that channel. Keys from the channel-level `msg` win over the global `msg`.

```json
{
  "type": "connect",
  "channels": {
    "my_dc": {
      "server_id": "111",
      "channel_id": "222",
      "msg": {
        "msg_format": "{msg}",
        "webhook_title": "{username} ({user_id}) @ {from}",
        "webhook_avatar": "{user_avatar}"
      }
    },
    "my_qq": {
      "group_id": "123456789",
      "msg": {
        "msg_format": "{username} ({user_id}): {msg}"
      }
    },
    "my_tg": {
      "chat_id": "-100987654321",
      "msg": {
        "msg_format": "{username} ({user_id}): {msg}"
      }
    }
  },
  "msg": {
    "msg_format": "{username} ({user_id}): {msg}"
  }
}
```

---

### forward (default)

Routes messages from one set of channels to another (unidirectional). Omit `"type"` or set it to `"forward"`.

```json
{
  "from": {
    "<instance_id>": { ...channel address... }
  },
  "to": {
    "<instance_id>": { ...channel address... }
  },
  "msg": { ...msg config... }
}
```

---

## msg config

Controls how the message is formatted when sent to a target.

| Key | Type | Default | Description |
|---|---|---|---|
| `msg_format` | string | `"{msg}"` | Template string for the message text |
| `webhook_title` | string | — | Discord webhook display name (Discord only) |
| `webhook_avatar` | string | — | Discord webhook avatar URL (Discord only) |

### msg_format template variables

| Variable | Description |
|---|---|
| `{platform}` | Platform name of the sender, e.g. `napcat`, `discord` |
| `{instance_id}` | Instance ID of the sender as defined in config.json |
| `{from}` | Alias for `{instance_id}` |
| `{username}` | Display name of the sender |
| `{user_id}` | Platform-native user ID |
| `{user_avatar}` | Avatar URL of the sender (may be empty) |
| `{msg}` | The message text content |

### Rich header tag

The `<richheader>` self-closing tag can be embedded anywhere in `msg_format`. The bridge strips it from the final text and passes its attributes to each driver for platform-native rendering.

```
<richheader title="..." content="..."/>
```

| Attribute | Description |
|---|---|
| `title` | Primary line — typically the sender name |
| `content` | Secondary line — typically the user ID or role |

Both attributes support the same `{variable}` substitutions as `msg_format`.

**Rendering by platform:**

| Platform | Rendered as |
|---|---|
| Telegram (with `rich_header_host`) | Small OG link-preview card above the message (avatar + title + content) |
| Telegram (fallback) | `**title** · *content*` HTML bold/italic header prepended to text |
| Discord | `**title** · *content*` Markdown bold/italic header prepended to text |
| QQ (NapCat) | `[title · content]` plain text prepended |
| Feishu / DingTalk | `[title · content]` plain text prepended |

**Example — rich header for Telegram with QQ-style plain text for QQ:**

```json
{
  "type": "connect",
  "channels": {
    "my_qq": {
      "group_id": "123456789",
      "msg": { "msg_format": "{username} ({user_id}): {msg}" }
    },
    "my_tg": {
      "chat_id": "-100987654321",
      "msg": {
        "msg_format": "<richheader title=\"{username}\" content=\"id: {user_id} platform: {platform}\"/> {msg}"
      }
    }
  }
}
```

On Telegram (when `rich_header_host` is configured) this produces a compact card with the sender's avatar and name displayed above the message body.

> **Note:** The rich header card is only shown for text-only messages. Messages that include media attachments fall back to the bold/italic HTML header in the caption.

---

### Examples

```json
{ "msg_format": "{username} ({user_id}): {msg}" }
```
```
Alice (123456789): hello everyone
```

```json
{ "msg_format": "[{platform}] {username}: {msg}" }
```
```
[discord] Alice: hello everyone
```

---

## Channel address keys

The channel address dict inside `from`, `to`, or `channels` depends on the driver:

| Platform | Keys |
|---|---|
| NapCat (QQ) | `group_id` |
| Discord | `server_id`, `channel_id` |
| Telegram | `chat_id` |
| Feishu | `chat_id` |
| DingTalk | `open_conversation_id` |

See each driver's page for details.

---

## Attachments

Media attachments (images, videos, voice, files) are automatically carried through the bridge. The bridge server downloads the file from the source and re-uploads it to the target platform — the target platform never fetches from the source URL directly. Each driver respects its configured `max_file_size`. If the file is too large or the download fails, a text fallback with the URL is appended to the message instead.

---

## Security: sensitive value detection

NextBridge automatically scans outgoing message text for strings that match credentials in `config.json` (bot tokens, secrets, webhook URLs, passwords). If a match is found, the message is **blocked** and a warning is logged:

```
[WRN] Message to 'my_discord' blocked: text contains a sensitive value from config
      (token/secret/webhook). Possible credential leak.
```

This prevents accidental leakage of credentials through the bridge (e.g. if a user sends a message containing a token they copied from somewhere).
