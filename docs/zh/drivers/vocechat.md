# VoceChat

VoceChat 驱动器将自托管的 [VoceChat](https://voce.chat/) 服务器与其他平台桥接。它运行一个 HTTP Webhook 端点接收 VoceChat 推送的消息，并通过 **机器人 REST API** 发送消息。

无需 NextBridge 现有依赖以外的额外安装包。

## 配置步骤

### 1. 创建机器人并获取 API Key

1. 以管理员身份登录 VoceChat，进入 **设置 → 机器人**。
2. 点击 **新建机器人**，填写名称和描述。
3. 复制生成的 **API Key** —— 这就是 `api_key` 配置值。

### 2. 配置 Webhook URL

1. 在机器人设置中，将 **Webhook URL** 设置为 NextBridge 端点地址，例如：
   `https://example.com/vocechat/webhook`
2. VoceChat 会发送 GET 请求来验证 URL 是否返回 HTTP 200，NextBridge 自动处理此验证。

### 3. 将机器人添加到频道

对于每个需要桥接的频道，在 VoceChat 的频道设置中点击 **添加机器人**，选择对应的机器人。

> Webhook 端点必须能从 VoceChat 服务器访问。开发阶段可使用反向代理或 ngrok。

## 配置项

在配置文件 `vocechat.<instance_id>` 下添加：

| 键 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `server_url` | 是 | — | VoceChat 服务器基础 URL，例如 `"https://chat.example.com"` |
| `api_key` | 是 | — | 机器人设置页面中的 Bot API Key |
| `listen_port` | 否 | `8091` | Webhook 监听的 HTTP 端口 |
| `listen_path` | 否 | `"/vocechat/webhook"` | Webhook 端点的 HTTP 路径 |
| `max_file_size` | 否 | `52428800`（50 MB）| 附件大小上限（字节） |

```json
{
  "vocechat": {
    "vc_main": {
      "server_url": "https://chat.example.com",
      "api_key": "your-bot-api-key",
      "listen_port": 8091
    }
  }
}
```

## 规则通道键

每个通道条目需要填写 `gid` 或 `uid` 之一：

| 键 | 说明 |
|---|---|
| `gid` | VoceChat 群组（频道）ID，整数 |
| `uid` | VoceChat 用户 ID（用于私信），整数 |

在 VoceChat 中打开频道时，频道 ID 显示在 URL 中（`/channel/{gid}`）。用户 ID 可在用户个人资料 URL 中找到。

```json
{
  "vc_main": {
    "gid": 2
  }
}
```

私信配置：

```json
{
  "vc_main": {
    "uid": 7910
  }
}
```

## 工作原理

**接收：** VoceChat 对每条新消息向 Webhook 端点 POST 一个 JSON 事件。驱动器会：
- 立即返回 HTTP 200，并在后台异步处理事件
- 处理 `text/plain` 和 `text/markdown` 两种内容类型作为文本消息
- 从 `/api/resource/file?path={path}` 下载 `vocechat/file` 类型附件并转发字节数据
- 跳过编辑、删除及系统事件（仅桥接 `normal` 和 `reply` 类型）
- 对于私信，使用发送者的 `uid` 作为通道进行路由

**发送：** 对于每条出站消息，驱动器会：
- 通过 `POST /api/bot/send_to_group/{gid}` 或 `/api/bot/send_to_user/{uid}` 发送文本，使用 `Content-Type: text/plain`（带 rich header 时使用 `text/markdown`）
- 先通过 `POST /api/bot/file/upload` 上传二进制附件，再发送 `vocechat/file` 引用消息
- 上传失败时回退为文本标签 `[类型: 文件名]`

## 注意事项

- 所有出站 API 调用均使用 `x-api-key` 请求头进行认证。
- VoceChat 支持 Markdown 格式。`rich_header` 前缀使用 `**粗体**` 和 `*斜体*`，并以 `Content-Type: text/markdown` 发送。
- 同一频道可添加多个机器人。驱动器会接收到所有用户（包括其他机器人）的消息 —— 如需限制，请在 VoceChat 的机器人权限设置中进行配置。
- 无需安装额外 Python 包，仅使用 NextBridge 已依赖的 `aiohttp`。
