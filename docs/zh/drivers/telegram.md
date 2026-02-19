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
| `rich_header_host` | 否 | — | Cloudflare 富头部 Worker 的基础 URL（见 [富头部](#富头部)） |

```json
{
  "telegram": {
    "tg_main": {
      "bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
      "max_file_size": 52428800,
      "rich_header_host": "https://richheader.yourname.workers.dev"
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

## 富头部

当 `msg_format` 中包含 `<richheader title="..." content="..."/>` 标签，且已配置 `rich_header_host` 时，NextBridge 会在 Telegram 消息文本上方显示一张**小型链接预览卡片**。卡片包含发送者的头像、名称（title）和副标题（content），视觉上紧凑且与消息正文明显区分。

其工作原理是通过 Cloudflare Worker 提供一个包含 [Open Graph](https://ogp.me/) 元标签的微型 HTML 页面。Telegram 获取这些标签后，以 `prefer_small_media` 样式将其渲染为显示在文字上方的链接预览卡片。

### Cloudflare Worker 部署步骤

::: tip 公共地址
我们提供一个公共地址，`https://richheader.siiway.top`。你可以直接使用它。
:::

1. 进入 [Cloudflare 控制台](https://dash.cloudflare.com/) → **Workers & Pages** → **创建**。
2. 将 [`cloudflare/richheader-worker.js`](https://github.com/siiway/NextBridge/blob/main/cloudflare/richheader-worker.js) 的内容粘贴到编辑器中并部署。
3. 复制 Worker 的 URL（如 `https://richheader.yourname.workers.dev`）。
4. 将该 URL 设置为 Telegram 实例配置中的 `rich_header_host`。

### msg_format 示例

```json
{
  "my_tg": {
    "chat_id": "-100987654321",
    "msg": {
      "msg_format": "<richheader title=\"{username}\" content=\"id: {user_id}\"/> {msg}"
    }
  }
}
```

### 回退行为

| 条件 | 行为 |
|---|---|
| 未配置 `rich_header_host` | 加粗/斜体 HTML 头部文字附加在消息文本前 |
| 消息包含媒体附件 | 同上（Telegram 的媒体 Caption 不支持链接预览） |

## 注意事项

- Telegram Bot 无法主动发起对话，请确保在运行 NextBridge 前 Bot 已在目标群组中。
- Bot 自身发送的消息不会被回显（Telegram 不会将 Bot 消息的事件推送给 Bot 自身）。
- 暂不获取发送者的头像 URL（需要额外的 API 调用）。
