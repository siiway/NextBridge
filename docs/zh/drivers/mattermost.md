# Mattermost

Mattermost 驱动器通过 **WebSocket API** 实时接收消息，通过 **REST API** 发送消息，连接到自托管或云端的 Mattermost 服务器。无需 NextBridge 现有依赖以外的额外安装包。

## 配置步骤

### 1. 创建机器人账号（推荐）

1. 以系统管理员身份登录，进入 **系统控制台 → 集成 → 机器人账号**。
2. 启用机器人账号，然后点击 **添加机器人账号**。
3. 填写用户名、显示名称和描述，点击 **创建机器人账号**。
4. 复制生成的 **令牌**，这就是 `token` 配置值。
5. 将机器人邀请到每个需要桥接的频道（点击频道名称 → **添加成员**）。

### 2. 个人访问令牌（替代方案）

如果机器人账号不可用：

1. 在 Mattermost 个人资料中，进入 **安全 → 个人访问令牌**。
2. 点击 **创建令牌**，输入名称并复制令牌。
3. 确保在 **系统控制台 → 集成** 中已启用个人访问令牌。

## 配置项

在配置文件 `mattermost.<instance_id>` 下添加：

| 键 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `server_url` | 是 | — | Mattermost 服务器基础 URL，例如 `"https://mattermost.example.com"` |
| `token` | 是 | — | 机器人令牌或个人访问令牌 |
| `max_file_size` | 否 | `52428800`（50 MB）| 附件大小上限（字节） |

```json
{
  "mattermost": {
    "mm_main": {
      "server_url": "https://mattermost.example.com",
      "token": "your-bot-or-personal-access-token"
    }
  }
}
```

## 规则通道键

| 键 | 说明 |
|---|---|
| `channel_id` | Mattermost 频道 ID |

查找频道 ID：打开频道，点击顶部频道名称，通过 URL 或 REST API（`/api/v4/channels/name/{team}/{channel}`）获取 ID。最简便的方式是通过 Mattermost REST API 查询。

```json
{
  "mm_main": {
    "channel_id": "abc123def456"
  }
}
```

## 工作原理

**接收：** 启动时，驱动器调用 `/api/v4/users/me` 获取机器人自身的用户 ID（用于过滤回声消息），随后连接到 Mattermost WebSocket 端点（`/api/v4/websocket`）并发送令牌认证挑战。对于每个 `posted` 事件：
- 通过检查 `type` 字段忽略系统消息（加入、离开、修改频道头部等）
- 文件附件通过 `/api/v4/files/{id}` 使用相同令牌下载，并作为二进制数据转发

连接断开后，WebSocket 会在 5 秒后自动重连。

**发送：** 对于每条出站消息，驱动器会：
1. 将二进制附件通过 multipart 上传到 `/api/v4/files`，收集返回的 `file_id`
2. 通过 `POST /api/v4/posts` 创建帖子，包含 `message` 和 `file_ids`
3. 无法获取的附件以文本标签形式附加（`[类型: 文件名]`）

## 注意事项

- 机器人账号必须**被邀请到每个需要接收和发送的频道**。未加入的频道消息不会通过 WebSocket 推送。
- Mattermost 使用标准 Markdown 格式。`rich_header` 前缀渲染为 `**标题** · *内容*`。
- 显示名称解析优先级：**昵称** → **名 + 姓** → **用户名**。
- 无需安装额外 Python 包，驱动器仅使用 NextBridge 已依赖的 `aiohttp`。
- 用户头像地址为 `/api/v4/users/{user_id}/image`，需要有效的会话才能访问；若 Mattermost 服务器未公开，下游平台的热链接头像可能显示异常。
