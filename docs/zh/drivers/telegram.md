# Telegram

Telegram 驱动器使用 [python-telegram-bot](https://python-telegram-bot.org/) 通过长轮询接收消息，并通过 Bot API 发送消息。

## 准备工作

1. 在 Telegram 上联系 [@BotFather](https://t.me/BotFather)，使用 `/newbot` 命令创建一个新 Bot。
2. 复制 BotFather 给你的 Bot Token。
3. 将 Bot 添加到你的群组，并赋予其读取消息的权限。
4. 获取群组的 Chat ID（提示：将群内消息转发给 [@userinfobot](https://t.me/userinfobot)，或通过 Bot API 的 `/getUpdates` 接口查询）。

## 配置项

在 `config.json` 的 `telegram.<实例ID>` 下添加：

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `bot_token` | 是 | — | 来自 @BotFather 的 Bot Token |
| `max_file_size` | 否 | `52428800`（50 MB） | 发送附件时单个文件的最大字节数 |

```json
{
  "telegram": {
    "tg_main": {
      "bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
      "max_file_size": 52428800
    }
  }
}
```

## 规则频道键

在 `rules.json` 的 `channels` 或 `from`/`to` 下使用：

| 键 | 说明 |
|---|---|
| `chat_id` | Telegram 聊天 ID。群组使用负数（如 `"-1002206757362"`） |

```json
{
  "tg_main": { "chat_id": "-1002206757362" }
}
```

## 接收的消息类型

| Telegram 类型 | 附件类型 |
|---|---|
| 图片（Photo） | `image` |
| 视频（Video） | `video` |
| 语音（Voice） | `voice` |
| 音频（Audio） | `voice` |
| 文件（Document） | `file` |
| 动图/GIF（Animation） | `video` |

带媒体的消息可能包含说明文字（Caption），该文字作为消息文本处理。

## 发送

| 附件类型 | Telegram API 方法 |
|---|---|
| `image` | `send_photo` |
| `voice` | `send_voice` |
| `video` | `send_video` |
| `file` | `send_document` |

消息文本作为第一个附件的 Caption 发送。若没有附件（或所有附件均失败），则以普通 `send_message` 发送。后续附件不再携带文本。

## 注意事项

- Telegram Bot 无法主动发起对话，请确保在运行 NextBridge 前 Bot 已在目标群组中。
- Bot 自身发送的消息不会被回显（Telegram 不会将 Bot 消息的事件推送给 Bot 自身）。
- 暂不获取发送者的头像 URL（需要额外的 API 调用）。
