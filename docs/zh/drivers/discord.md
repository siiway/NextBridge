> 本文档由 AI 编写，已经人工审核。

# Discord

Discord 驱动器通过 Discord 网关（Bot Token）接收消息，并支持通过 **Webhook** 或 **Bot** 两种方式发送消息。

## 准备工作

1. 在 [Discord 开发者门户](https://discord.com/developers/applications) 创建一个 Bot 应用。
2. 在 **Bot** 页面中启用 **Message Content Intent**（消息内容权限）。
3. 复制 Bot Token。
4. 如需 Webhook 发送：在频道设置中创建 Webhook 并复制其 URL。
5. 将 Bot 邀请至你的服务器，确保其拥有 `Read Messages` 和 `Send Messages` 权限。

## 配置项

在 `config.json` 的 `discord.<实例ID>` 下添加：

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `bot_token` | 否* | — | Discord Bot Token，接收消息和 `bot` 发送模式均需此项 |
| `send_method` | 否 | `webhook` | `"webhook"` 或 `"bot"` |
| `max_file_size` | 否 | `8388608`（8 MB） | 发送附件时单个文件的最大字节数 |
| `cqface_webhook_fallback` | 否 | `"unicode"` | `"bot"` 或 `"unicode"`（默认）。通过 Webhook 发送时，遇到 CQ 表情标记的处理方式。`"bot"` 在有 CQ 表情时通过 Bot 发送；`"unicode"` 渲染为 unicode 表情回退。 |
| `send_replies_as_bot` | 否 | `true` | 为 `true` 时，回复消息在 Bot 已连接情况下会优先通过 Bot 发送，即使 `send_method` 为 `"webhook"`。原因是 Discord Webhook 模式不支持指定回复目标消息。需配置 `bot_token` 才会生效。 |
| `allow_mentions_everyone` | 否 | `false` | 允许桥接消息中的 `@everyone`/`@here` 提及 |
| `allow_mentions_users` | 否 | `true` | 允许桥接消息中的 `@user` 提及 |
| `allow_mentions_roles` | 否 | `false` | 允许桥接消息中的 `@role` 提及 |
| `sanitize_mass_mentions` | 否 | `true` | 中和传出消息文本中的 `@everyone`/`@here`（替换为纯文本） |
| `auto_link_image_hosts` | 否 | `["discordmedia.com", "tenor.com"]` | 接收“仅包含一个 URL”的消息时使用的 host 白名单。host 匹配时，NextBridge 会尝试将 URL 解析为图片并作为图片附件桥接。包含子域名。设为 `[]` 可关闭。 |
| `auto_link_image_show_original_url` | 否 | `true` | 自动链接转图片成功时，是否在图片前保留原 URL。设为 `false` 时只桥接解析出的图片。 |
| `enable_recall` | 否 | `true` | 是否同步消息撤回。启用后，Discord 上的删除会被检测并桥接到其他平台，其他平台的撤回也会应用到 Discord。设为 `false` 可禁用撤回同步。 |
| `media_proxy` | 否 | — | 仅用于获取媒体/附件的代理 URL。未设置时默认跟随 `proxy`。 |
| `proxy` | 否 | — | 所有 Discord API 请求的代理 URL（例如：`http://proxy.example.com:8080` 或 `socks5://proxy.example.com:1080`）。设置后，代理连接将禁用 SSL 验证。设置为 `null` 可显式禁用此实例的代理（忽略全局代理设置）。 |

\* 接收消息时需要提供 `bot_token`。仅使用 webhook 发送时，只需在规则中提供 `webhook_url`。

```json
{
  "discord": {
    "dc_main": {
      "bot_token": "your_bot_token",
      "send_method": "webhook",
      "max_file_size": 8388608,
      "auto_link_image_hosts": ["discordmedia.com", "tenor.com"],
      "auto_link_image_show_original_url": true,
      "proxy": "http://proxy.example.com:8080"
    }
  }
}
```

## 发送模式

### webhook（默认）

通过 Discord Webhook URL 发送消息。支持通过规则 `msg` 配置中的 `webhook_title` 和 `webhook_avatar` 为每条消息设置自定义显示名和头像。

说明：Discord Webhook 模式不支持指定回复目标消息。若需要桥接后的回复在 Discord 中显示为“回复”，请启用 `send_replies_as_bot` 并配置 `bot_token`。

```json
"msg": {
  "msg_format": "{msg}",
  "webhook_title": "{user} @ {from}",
  "webhook_avatar": "{user_avatar}"
}
```

### bot

通过 Bot 自身发送消息，需要提供 `bot_token`。不支持每条消息自定义用户名和头像。

## 规则频道键

在 `rules.json` 的 `channels` 或 `from`/`to` 下使用：

| 键 | 说明 |
|---|---|
| `server_id` | Discord 服务器（Guild）ID |
| `channel_id` | Discord 频道 ID |
| `webhook_url` | 此频道的 Webhook URL（使用 webhook 发送模式时必填） |

```json
{
  "dc_main": {
    "server_id": "1061629481267245086",
    "channel_id": "1269706305661309030",
    "webhook_url": "https://discord.com/api/webhooks/ID/TOKEN"
  }
}
```

## 额外 msg 键

以下键可放在规则的 `msg` 块中，由 Discord 驱动器读取：

| 键 | 说明 |
|---|---|
| `webhook_msg_format` | 通过 Webhook 发送时覆盖 `msg_format`，支持相同模板变量。 |
| `bot_msg_format` | 通过 Bot 发送时覆盖 `msg_format`（包括 `cqface_webhook_fallback` 或 `send_replies_as_bot` 触发的情形），支持相同模板变量。 |
| `webhook_title` | Webhook 消息上显示的用户名（仅 `send_method: "webhook"` 时生效） |
| `webhook_avatar` | Webhook 消息上显示的头像 URL（仅 `send_method: "webhook"` 时生效） |

所有键均支持与 `msg_format` 相同的模板变量。

## CQ 表情 Emoji（discord_emojis.json）

使用 NapCat 驱动器的 `cqface_mode: "emoji"` 时，Discord 驱动器会将 `:cqface<id>:` 标记解析为 Discord 自定义 Emoji（`<:cqface306:emoji_id>`），解析依赖本地 JSON 文件。配置步骤如下：

1. 在浏览器中访问 `https://discord.com/developers/applications/<your_app_id>/emojis`。
2. 打开浏览器 **Network**（网络）面板（F12 → Network）。
3. 刷新页面。
4. 找到请求 `emojis` 端点的记录（例如 `https://discord.com/api/v9/applications/1343923133370994750/emojis`）。
5. 复制该请求的 JSON 响应体，保存为数据目录下的 `discord_emojis.json`（默认路径：`data/discord_emojis.json`）。

若文件不存在或未找到对应 Emoji，将回退为纯文本 `:cqface<id>:`。

## 消息编辑同步

当 Discord 消息被编辑后，NextBridge 会检测到变更，并自动更新其他平台上对应的桥接消息。

**前提条件：**
- 必须配置 `bot_token` 才能从 Discord 接收编辑事件。
- 纯 Webhook 模式（无 `bot_token`）无法接收来自 Discord 的编辑事件，但仍可将其他平台的编辑同步应用至 Discord。

**编辑如何应用到 Discord：**
- 如果频道配置了 `webhook_url`，NextBridge 使用 Discord Webhook 编辑 API（`PATCH /webhooks/{id}/{token}/messages/{message_id}`）。
- 否则，如果配置了 `bot_token`，Bot 会直接获取并编辑对应消息。

编辑同步仅同步文本内容，不修改附件。

仅当消息的可见内容（文本或附件）确实发生变化时才会触发编辑同步。诸如**标注（置顶）消息**、或**消息中的链接自动生成预览（Embed）**等操作不会改变文本内容，因此不会被误判为编辑同步到其他平台。

## 消息撤回同步

当 Discord 消息被删除后，NextBridge 会检测到该操作，并自动删除其他平台上对应的桥接消息。

**前提条件：**
- 必须配置 `bot_token` 才能从 Discord 接收删除事件（通过网关的原始删除事件检测，即使消息未缓存也可捕获）。
- 纯 Webhook 模式（无 `bot_token`）无法检测 Discord 上的删除，但仍可将其他平台的撤回应用至 Discord。

**撤回如何应用到 Discord：**
- 如果频道配置了 `webhook_url`，NextBridge 使用 Discord Webhook 删除 API（`DELETE /webhooks/{id}/{token}/messages/{message_id}`）。
- 否则，如果配置了 `bot_token`，Bot 会直接获取并删除对应消息。

将 `enable_recall` 设为 `false` 可禁用撤回的检测与应用。

## 贴纸与自定义表情桥接

Discord 贴纸（Sticker）和自定义表情（Custom Emoji）会自动转换为图片/GIF，作为附件桥接到其他平台。

| 类型 | 格式 | 桥接方式 |
|---|---|---|
| 贴纸 | PNG / APNG | 作为 `image` 附件，使用贴纸 CDN URL |
| 贴纸 | GIF | 作为 `image` 附件（GIF） |
| 贴纸 | Lottie | 不支持直接桥接为图片，使用文本 `[Sticker: 名称]` 作为回退 |
| 自定义表情 | 静态（`<:name:id>`） | 作为 `image` 附件（PNG），从 Discord CDN 下载 |
| 自定义表情 | 动态（`<a:name:id>`） | 作为 `image` 附件（GIF），从 Discord CDN 下载 |

无需额外配置即可使用，所有贴纸和自定义表情均通过 `bot_token` 接收后自动处理。

## 注意事项

- Bot 发送的消息不会被再次桥接（Webhook 回显不会触发事件）。
- 仅包含一个 `auto_link_image_hosts` 白名单 URL 的消息会按 Discord 客户端预览方式解析。直接图片 URL 会作为图片桥接；HTML 页面会尝试读取 `og:image`/`twitter:image`。解析失败时保留原始文本桥接。
- 文件会被下载后通过 multipart 表单重新上传。若文件超过 `max_file_size`，其 URL 将以文字形式附加到消息中。
