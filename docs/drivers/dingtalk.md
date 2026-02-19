# DingTalk

The DingTalk driver receives messages via an HTTP webhook (outgoing robot) and sends via the DingTalk Robot v1.0 API using [alibabacloud-dingtalk](https://github.com/aliyun/alibabacloud-dingtalk-sdk).

## Setup

1. In the [DingTalk Developer Console](https://open-dev.dingtalk.com), create an internal app.
2. Under **Robot**, create a robot and configure **Message Receive Mode** → **HTTP Mode**.
3. Set the message receive URL to `http://your-host:8082/dingtalk/event`.
4. Copy the **App Key**, **App Secret**, and **Robot Code**.
5. Optionally enable webhook signing and copy the **Signing Secret**.
6. Add the bot to the target group.

::: warning Public endpoint required
DingTalk must be able to reach your HTTP endpoint from the internet. Use a reverse proxy, tunnel (e.g. ngrok), or deploy on a public server.
:::

## Config keys

Add under `dingtalk.<instance_id>` in `config.json`:

| Key | Required | Default | Description |
|---|---|---|---|
| `app_key` | Yes | — | DingTalk app key |
| `app_secret` | Yes | — | DingTalk app secret |
| `robot_code` | Yes | — | Robot code, required for sending messages |
| `signing_secret` | No | — | Webhook signing secret; skips signature verification if absent |
| `listen_port` | No | `8082` | HTTP port to listen on for incoming events |
| `listen_path` | No | `"/dingtalk/event"` | HTTP path for incoming events |

```json
{
  "dingtalk": {
    "dt_main": {
      "app_key": "dingxxxxxxxxxx",
      "app_secret": "your_app_secret",
      "robot_code": "your_robot_code",
      "signing_secret": "your_signing_secret",
      "listen_port": 8082,
      "listen_path": "/dingtalk/event"
    }
  }
}
```

## Rule channel keys

Use under `channels` or `from`/`to` in `rules.json`:

| Key | Description |
|---|---|
| `open_conversation_id` | DingTalk open conversation ID of the target group |

```json
{
  "dt_main": { "open_conversation_id": "cidXXXXXXXXXXXXXXX" }
}
```

The `open_conversation_id` is included in the webhook event payload of messages sent by users in the group (`openConversationId` field). You can also find it in the DingTalk developer console.

## Notes

- Currently only **text messages** are received. Rich-media message types are ignored on the receive side.
- Outgoing attachments are sent as URLs appended to the message text.
- OAuth 2.0 access tokens are cached and automatically refreshed 60 seconds before expiry.
- If `signing_secret` is not set, webhook signature verification is skipped. It is strongly recommended to set a signing secret in production.
