# 规则配置参考

消息路由在 `data/rules.json` 中定义：

```json
{
  "rules": [ ...规则对象... ]
}
```

规则按顺序对每条收到的消息逐一匹配，一条消息可以命中多条规则。

---

## 规则类型

### connect（互联）

将所有列出的频道**双向连通**。任意一个频道收到消息后，都会转发给其余所有频道。

```json
{
  "type": "connect",
  "channels": {
    "<实例ID>": { ...频道地址... },
    "<实例ID>": { ...频道地址... }
  },
  "msg": { ...全局消息格式配置... }
}
```

#### 按频道覆盖消息格式

每个频道条目可以包含一个 `"msg"` 键，用于覆盖发送**到该频道**时使用的全局 `"msg"` 配置。频道级别的 `msg` 中的键优先于全局 `msg`。

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

### forward（转发，默认）

将消息从一组频道单向转发到另一组频道。省略 `"type"` 字段或将其设为 `"forward"` 均可。

```json
{
  "from": {
    "<实例ID>": { ...频道地址... }
  },
  "to": {
    "<实例ID>": { ...频道地址... }
  },
  "msg": { ...消息格式配置... }
}
```

---

## msg 配置

控制消息发送到目标平台时的格式化方式。

| 键 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `msg_format` | string | `"{msg}"` | 消息文本的模板字符串 |
| `webhook_title` | string | — | Discord Webhook 显示名称（仅 Discord 生效） |
| `webhook_avatar` | string | — | Discord Webhook 头像 URL（仅 Discord 生效） |

### msg_format 模板变量

| 变量 | 说明 |
|---|---|
| `{platform}` | 发送方的平台名，如 `napcat`、`discord` |
| `{from}` | 发送方的实例 ID（与 config.json 中定义一致） |
| `{username}` | 发送者的显示名称 |
| `{user_id}` | 平台原生用户 ID |
| `{user_avatar}` | 发送者的头像 URL（可能为空） |
| `{msg}` | 消息文本内容 |

### 富头部标签（Rich Header）

可以在 `msg_format` 的任意位置嵌入 `<richheader>` 自闭合标签。桥接器会将其从最终文本中提取出来，并将属性传递给各驱动器，由各平台以原生方式渲染。

```
<richheader title="..." content="..."/>
```

| 属性 | 说明 |
|---|---|
| `title` | 主行内容，通常为发送者名称 |
| `content` | 次行内容，通常为用户 ID 或角色 |

两个属性均支持与 `msg_format` 相同的 `{变量}` 替换。

**各平台渲染方式：**

| 平台 | 渲染形式 |
|---|---|
| Telegram（已配置 `rich_header_host`） | 消息上方的小型 OG 链接预览卡片（含头像、标题、副标题） |
| Telegram（回退模式） | 加粗/斜体 HTML 头部文字，附加在消息文本前 |
| Discord | `**title** · *content*` Markdown 加粗/斜体，附加在文本前 |
| QQ（NapCat） | `[title · content]` 纯文本，附加在消息前 |
| 飞书 / 钉钉 | `[title · content]` 纯文本，附加在消息前 |

**示例——Telegram 使用富头部，QQ 使用纯文本格式：**

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

在 Telegram 上（已配置 `rich_header_host` 时），将在消息正文上方显示一张带有发送者头像和名称的紧凑卡片。

> **注意：** 富头部卡片仅在纯文字消息中显示。包含媒体附件的消息将回退为在 Caption 中附加加粗/斜体头部文字。

---

### 示例

```json
{ "msg_format": "{username} ({user_id}): {msg}" }
```
```
Alice (123456789): 大家好
```

```json
{ "msg_format": "[{platform}] {username}: {msg}" }
```
```
[discord] Alice: 大家好
```

---

## 频道地址键

`from`、`to` 或 `channels` 中的频道地址字典，其键名因驱动器而异：

| 平台 | 键名 |
|---|---|
| NapCat (QQ) | `group_id` |
| Discord | `server_id`、`channel_id` |
| Telegram | `chat_id` |
| 飞书 | `chat_id` |
| 钉钉 | `open_conversation_id` |

详细说明请参阅各驱动器页面。

---

## 附件（媒体文件）

消息中携带的媒体附件（图片、视频、语音、文件）会自动通过桥接传递。桥接服务器负责从源平台下载文件并重新上传到目标平台——目标平台不会直接访问源平台的 URL。上限由各驱动器的 `max_file_size` 配置决定。若文件超过大小限制或下载失败，则将 URL 以文字形式附加到消息末尾。

---

## 安全：敏感信息检测

NextBridge 会自动扫描每条即将发出的消息文本，检查其中是否包含与 `config.json` 中凭据（Bot Token、Secret、Webhook URL、密码等）匹配的字符串。若匹配成功，该消息将被**拦截**，并在控制台输出警告：

```
[WRN] Message to 'my_discord' blocked: text contains a sensitive value from config
      (token/secret/webhook). Possible credential leak.
```

此机制可防止凭据通过消息桥接意外泄露（例如：用户将复制的 Token 直接发送到聊天群中）。
