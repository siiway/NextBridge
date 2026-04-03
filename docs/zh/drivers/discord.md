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
| `cqface_webhook_fallback` | 否 | `unicode` | 控制消息中包含 `:cqface<id>:` 标记且使用 Webhook 发送时的回退方式。设为 `"bot"` 时会改用 Bot 发送；设为 `"unicode"` 时仍使用 Webhook，并按 `db/cqface-map.yaml` 中的 Unicode 映射替换标记。 |
| `send_replies_as_bot` | 否 | `true` | 为 `true` 时，回复消息在 Bot 已连接情况下会优先通过 Bot 发送，即使 `send_method` 为 `"webhook"`。原因是 Discord Webhook 模式不支持指定回复目标消息。需配置 `bot_token` 才会生效。 |
| `allow_mentions_everyone` | 否 | `false` | 控制出站消息是否允许触发 Discord 的 `@everyone` / `@here` 提醒。 |
| `allow_mentions_users` | 否 | `true` | 控制出站消息是否允许提及用户（`<@id>`）。 |
| `allow_mentions_roles` | 否 | `false` | 控制出站消息是否允许提及身份组（`<@&id>`）。 |
| `sanitize_mass_mentions` | 否 | `true` | 为 `true` 时，会对出站文本中的 `@everyone` / `@here` 做去活化，避免群体提醒。 |
| `proxy` | 否 | — | 所有 Discord API 请求的代理 URL（例如：`http://proxy.example.com:8080` 或 `socks5://proxy.example.com:1080`）。设置后，代理连接将禁用 SSL 验证。设置为 `null` 可显式禁用此实例的代理（忽略全局代理设置）。 |

\* 接收消息时需要提供 `bot_token`。仅使用 webhook 发送时，只需在规则中提供 `webhook_url`。

```json
{
  "discord": {
    "dc_main": {
      "bot_token": "your_bot_token",
      "send_method": "webhook",
      "max_file_size": 8388608,
      "cqface_webhook_fallback": "unicode",
      "allow_mentions_everyone": false,
      "allow_mentions_users": true,
      "allow_mentions_roles": false,
      "sanitize_mass_mentions": true,
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
| `bot_msg_format` | 通过 Bot 发送时覆盖 `msg_format`（包括 `cqface_webhook_fallback: "bot"` 或 `send_replies_as_bot` 触发的情形），支持相同模板变量。 |
| `webhook_title` | Webhook 消息上显示的用户名（仅 `send_method: "webhook"` 时生效） |
| `webhook_avatar` | Webhook 消息上显示的头像 URL（仅 `send_method: "webhook"` 时生效） |

所有键均支持与 `msg_format` 相同的模板变量。

## CQ 表情 Emoji（discord_emojis.json）

使用 NapCat 驱动器的 `cqface_mode: "emoji"` 时，Discord 驱动器在 Bot 发送时会将 `:cqface<id>:` 标记解析为 Discord 自定义 Emoji（`<:cqface306:emoji_id>`）。如果找不到自定义 Emoji，或 Webhook 回退模式选择了 `unicode`，则会使用 `db/cqface-map.yaml` 里的 Unicode 映射。配置本地自定义 Emoji 的步骤如下：

1. 在浏览器中访问 `https://discord.com/developers/applications/<your_app_id>/emojis`。
2. 打开浏览器 **Network**（网络）面板（F12 → Network）。
3. 刷新页面。
4. 找到请求 `emojis` 端点的记录（例如 `https://discord.com/api/v9/applications/1343923133370994750/emojis`）。
5. 复制该请求的 JSON 响应体，保存为数据目录下的 `discord_emojis.json`（默认路径：`data/discord_emojis.json`）。

若文件不存在或未找到对应 Emoji，将回退为 `db/cqface-map.yaml` 里的 Unicode 映射。

## 注意事项

- Bot 发送的消息不会被再次桥接（Webhook 回显不会触发事件）。
- 文件会被下载后通过 multipart 表单重新上传。若文件超过 `max_file_size`，其 URL 将以文字形式附加到消息中。
