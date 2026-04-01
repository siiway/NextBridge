> This document was written by AI and has been manually reviewed.

# WhatsApp

The WhatsApp driver uses [neonize](https://github.com/krypton-byte/neonize) — Python bindings for [go-whatsapp (whatsmeow)](https://github.com/tulir/whatsmeow) — to connect directly to WhatsApp Web. No Node.js is required.

## Setup

1. Add a WhatsApp instance to your `config.json` (see below).
2. Start NextBridge. On first run, a QR code is printed to the terminal.
3. Open WhatsApp on your phone → **Linked Devices** → **Link a Device**, then scan the QR code.
4. Auth state is saved to the `storage_dir` SQLite file; you won't need to scan again unless you log out.

## System Requirements

neonize requires certain system libraries depending on your platform:

- **Linux (Ubuntu/Debian)**:
  ```bash
  sudo apt install libmagic1
  ```

- **Linux (Fedora/RHEL)**:
  ```bash
  sudo dnf install file-libs
  ```

- **macOS**:
  ```bash
  brew install libmagic
  ```

- **Windows**: `python-magic-bin` is installed automatically with neonize.

## Config keys

Add under `whatsapp.<instance_id>` in `config.json`:

| Key | Required | Default | Description |
|---|---|---|---|
| `storage_dir` | No | `~/.nextbridge/whatsapp/<instance_id>.db` | Path to the SQLite file that stores authentication state |

```json
{
  "whatsapp": {
    "wa_main": {
      "storage_dir": "/path/to/whatsapp/wa_main.db"
    }
  }
}
```

## Rule channel keys

Use under `channels` or `from`/`to` in `rules.json`:

| Key | Description |
|---|---|
| `chat_id` | WhatsApp JID string. Use `<phone>@s.whatsapp.net` for DMs or `<group-id>@g.us` for groups |

```json
{
  "wa_main": { "chat_id": "1234567890@s.whatsapp.net" }
}
```

## Received message types

| WhatsApp type | Attachment type | Notes |
|---|---|---|
| Text | — | Plain conversation or extended text (reply, link preview) |
| Image | `image` | Caption becomes message text |
| Video | `video` | Caption becomes message text |
| Voice / Audio | `voice` | Text set to `[Voice Message]` |
| Document | `file` | Caption becomes message text; filename preserved |

## Sending

Outgoing messages are sent as plain text. If the message includes attachments bridged from another platform, they are appended as text fallbacks:

```
[Image: photo.jpg]
[File: document.pdf]
```

Native media sending (uploading images/files to WhatsApp) is not yet implemented.

## Notes

- **WhatsApp account required**: This driver uses the WhatsApp Web multi-device protocol (not the Business API). A personal WhatsApp account must be linked via QR code.
- **One session at a time**: Linking NextBridge counts as one of your Linked Devices. You can still use WhatsApp on your phone normally.
- **Group JIDs**: To find a group's JID, check the logs after the first message is received — the `chat_id` is printed.
- **Own messages are filtered**: Messages sent by the linked account are ignored.
- **Status broadcasts** (`status@broadcast`) are ignored automatically.
