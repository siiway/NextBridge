# Rocket.Chat

Rocket.Chat 驱动通过**外发 Webhook（Outgoing Webhook）**接收消息，支持两种发送模式：**API 模式**（使用机器人凭证通过 REST API 发送，默认）和 **Webhook 模式**（向 Incoming Webhook URL 发送）。无需额外安装 Python 依赖包。

## 配置步骤

### 1. 创建机器人账号（API 模式必需；Webhook 模式亦推荐）

1. 以管理员身份登录，进入**管理 → 用户 → 新建用户**。
2. 填写用户名、姓名和邮箱；在**角色**中添加 **bot**。
3. 设置密码后保存。
4. 前往**管理 → 个人访问令牌**，为机器人用户创建一个令牌，分别复制**令牌（token）**和**用户 ID**（在**管理 → 用户 → （机器人用户）→ _id** 中查看）。

### 2. 配置外发 Webhook（接收）

1. 进入**管理 → 集成 → 新建集成 → 外发 WebHook**。
2. 填写以下内容：
   - **触发事件**：消息已发送
   - **启用**：是
   - **频道**：留空表示监听所有频道，或填写 `#channel-name` 限定范围
   - **URL**：`http(s)://<服务器地址>:<listen_port><listen_path>`
     例如：`https://bridge.example.com:8093/rocketchat/webhook`
   - **令牌**：生成或手动输入一个密钥，并复制到配置文件的 `webhook_token` 字段
3. 保存集成配置。

### 3a. API 发送模式——无需额外设置

直接使用机器人账号的凭证即可。

### 3b. Webhook 发送模式——创建 Incoming Webhook

1. 进入**管理 → 集成 → 新建集成 → 传入 WebHook**。
2. 将**启用**设为是，选择一个默认频道（运行时会被覆盖，任意选择即可）。
3. 复制生成的 **Webhook URL**，将其填入配置文件的 `webhook_url` 字段。

## 配置项

在配置文件的 `rocketchat.<实例ID>` 下添加以下内容：

| 配置项 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `send_method` | 否 | `"api"` | `"api"` 或 `"webhook"` |
| `server_url` | API 模式必填 | `""` | 服务器基础 URL，例如 `"https://chat.example.com"`，同时用于下载接收到的附件 |
| `auth_token` | API 模式必填 | `""` | 机器人账号的个人访问令牌 |
| `user_id` | API 模式必填 | `""` | 机器人账号的用户 ID |
| `webhook_url` | Webhook 模式必填 | `""` | `send_method="webhook"` 时的 Incoming Webhook URL |
| `listen_port` | 否 | `8093` | 接收外发 Webhook 的 HTTP 端口 |
| `listen_path` | 否 | `"/rocketchat/webhook"` | 接收外发 Webhook 的 HTTP 路径 |
| `webhook_token` | 否 | `""` | 外发 Webhook 令牌，用于验证请求来源 |
| `max_file_size` | 否 | `52428800`（50 MB） | 发送附件时的最大字节数 |

**API 模式示例：**

```json
{
  "rocketchat": {
    "rc_main": {
      "server_url": "https://chat.example.com",
      "auth_token": "your-personal-access-token",
      "user_id": "bot-user-id",
      "webhook_token": "your-outgoing-webhook-token"
    }
  }
}
```

**Webhook 模式示例：**

```json
{
  "rocketchat": {
    "rc_wh": {
      "send_method": "webhook",
      "webhook_url": "https://chat.example.com/hooks/your-incoming-webhook-id/token",
      "webhook_token": "your-outgoing-webhook-token"
    }
  }
}
```

## 规则频道键

| 键名 | 是否必填 | 说明 |
|---|---|---|
| `room_id` | 仅 API 模式 | Rocket.Chat 房间 ID，例如 `"GENERAL"` |

通过以下接口查询房间 ID：

```
GET /api/v1/channels.info?roomName=general
```

响应中的 `_id` 字段即为 `room_id`。私信房间可通过 `/api/v1/dm.list` 查询。

在 Webhook 模式下无需 `room_id`，目标频道由 Rocket.Chat 中的 Incoming Webhook 配置决定。

```json
{
  "rc_main": { "room_id": "GENERAL" }
}
```

## 工作原理

**接收：** Rocket.Chat 在有消息发出时，会向配置的 URL 发送 JSON 格式的 POST 请求。驱动会：
- 校验请求体中的 `token` 字段是否与 `webhook_token` 匹配（如已设置）
- 过滤 `user_id` 与机器人自身相同的消息（API 模式）
- 当设置了 `auth_token` 时，使用机器人凭证下载文件附件
- 将规范化的消息转发至消息桥接中心

**发送——API 模式：**
1. 通过 `POST /api/v1/chat.postMessage` 发送文本（配置后附带 `alias`/`avatar` 覆盖）
2. 通过 `POST /api/v1/rooms.upload/{room_id}` 以 multipart 方式上传二进制附件，文件在 RC 中内嵌显示
3. 无法获取的附件将以文本标签形式发送（`[类型: 文件名]`）

**发送——Webhook 模式：**
1. 向 Incoming Webhook URL 发送 JSON（配置后附带 `username`/`icon_url` 覆盖）
2. 含公开 URL 的附件以 `attachments` 数组形式附加，图片将内嵌显示
3. 仅含字节数据（无公开 URL）的附件将回退为文本标签——Incoming Webhook 无法上传文件

## 每条消息独立设置用户名和头像

两种发送模式均支持单条消息覆盖发送者身份信息。在规则的 `msg` 块中配置：

```json
{
  "rules": [{
    "from": { "dc": { "channel_id": "123" } },
    "to":   { "rc_main": { "room_id": "GENERAL" } },
    "msg": {
      "msg_format": "[Discord] {username}: {msg}",
      "rc_alias":   "{username}",
      "rc_avatar":  "{user_avatar}"
    }
  }]
}
```

| 键名 | 说明 |
|---|---|
| `rc_alias` | 消息显示的用户名（例如 `"{username}"`） |
| `rc_avatar` | 消息显示的头像 URL（例如 `"{user_avatar}"`）。必须为 HTTPS URL，否则忽略。 |

在 API 模式下，机器人账号须拥有 **bot** 角色，`alias`/`avatar` 覆盖才会生效。

## 注意事项

- API 模式下，机器人用户必须是每个目标房间的**成员**。通过**房间信息 → 成员 → 添加**将机器人加入房间。
- Webhook 模式下无需 `room_id` 频道键，目标频道由 Rocket.Chat 中的 Incoming Webhook 配置决定。
- 请确保监听 URL 可从 Rocket.Chat 服务器访问。若使用反向代理，请确认路径已正确转发。
- 个人访问令牌默认不过期；若设置了有效期，过期后请重新生成并更新配置。
