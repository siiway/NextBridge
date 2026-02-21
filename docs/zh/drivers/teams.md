# Microsoft Teams

Teams 驱动器通过 **Azure Bot Framework** 将 Microsoft Teams 与其他平台桥接。它运行一个 HTTP 服务器接收 Teams 推送的消息，并使用 **Bot Connector REST API** 发送回复。

## 前置条件

1. 在 [Azure 门户](https://portal.azure.com/) 创建一个 **Azure Bot** 资源。
2. 在机器人资源中，记录 **应用程序（客户端）ID**，并在 *证书和密钥* 下创建一个 **客户端密钥**。
3. 在 *通道* 中，添加 **Microsoft Teams** 通道。
4. 将机器人的 **消息传递终结点** 设置为 `https://<your-host>:<listen_port><listen_path>`。
   终结点必须通过 HTTPS 公开可访问（开发阶段可使用 nginx 反向代理或 ngrok 等隧道工具）。

## 配置项

在 `config.json` 中 `teams.<instance_id>` 下添加：

| 键 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `app_id` | 是 | — | Azure 机器人应用程序（客户端）ID |
| `app_secret` | 是 | — | Azure 机器人客户端密钥 |
| `listen_port` | 否 | `3978` | 驱动器监听传入 Activity 的端口 |
| `listen_path` | 否 | `"/api/messages"` | 消息传递终结点的 HTTP 路径 |
| `max_file_size` | 否 | `20971520` | 附件大小上限（字节），默认 20 MB |

```json
{
  "teams": {
    "my_teams": {
      "app_id":     "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "app_secret": "your-client-secret"
    }
  }
}
```

## 规则通道键

| 键 | 说明 |
|---|---|
| `service_url` | 来自传入 Activity 的 Bot Framework 服务 URL（例如 `"https://smba.trafficmanager.net/amer/"`） |
| `conversation_id` | 来自传入 Activity 的 Teams 会话 ID |

这两个值在驱动器收到的每条消息中均自动存在。可从日志中复制，或使用 webhook 捕获工具在收到第一条消息时获取。

```json
{
  "teams": {
    "my_teams": {
      "service_url":     "https://smba.trafficmanager.net/amer/",
      "conversation_id": "19:abc123@thread.tacv2"
    }
  }
}
```

## 工作原理

**接收：** 驱动器启动 aiohttp HTTP 服务器。用户在 Teams 中发送消息时，Bot Framework 将 JSON *Activity* POST 到该终结点。驱动器会：
- 忽略非消息事件（正在输入提示、表情回应等）
- 从消息正文中去除 @机器人 的提及文本
- 跳过机器人自身发送的消息（通过 `28:` ID 前缀识别）
- 将规范化消息转发到桥接核心

**发送：** 对于每条出站消息，驱动器会：
1. 从 Microsoft Identity 获取 OAuth2 客户端凭据令牌（自动缓存并刷新）
2. 向 `{service_url}/v3/conversations/{conversation_id}/activities` POST 一个 `message` Activity
3. 对于图片，发送嵌入 base64 图像的 Adaptive Card
4. 对于其他文件类型，发送文本标签 `[类型: 文件名]`（Teams 文件上传需要 SharePoint 集成，单纯 REST API 无法实现）

## 注意事项

- 消息传递终结点在生产环境中**必须使用 HTTPS**；Teams 会拒绝纯 HTTP 终结点。
- `service_url` 因租户所在区域而异，请使用该会话第一条传入 Activity 中返回的值。
- `rich_header` 前缀使用 Markdown 粗体/斜体格式（`**标题** · *内容*`）渲染。
- Teams 对 Adaptive Card 有约 28 KB 的载荷限制，超大图片将改为文本标签发送。
