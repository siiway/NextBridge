# 飞书 / Lark

飞书驱动器支持两种接收模式，并通过飞书 IM v1 API 使用 [lark-oapi](https://github.com/larksuite/oapi-sdk-python) 发送消息。

飞书（中国大陆）和 Lark（国际版）使用相同的 API，共用同一驱动器。

## 应用权限

在飞书/Lark 开发者后台的**权限管理**中，为应用开通以下权限范围，并发布应用版本：

| 权限 | 用途 |
|---|---|
| `im:message`（或 `im:message:send`） | **发送**消息——出站桥接必需 |
| `im:message:receive_v1` | **接收**消息事件 |
| `im:resource`（或 `im:resource:upload`） | 转发附件时上传图片和文件 |
| `contact:contact.base:readonly` | 将发送者 open_id 解析为显示名称和头像 |

::: tip
如果日志中出现 `Access denied` 错误，说明应用版本缺少上述一个或多个权限范围。请在**权限管理**中添加对应权限后重新发布应用版本。

`contact:contact.base:readonly` 为可选权限——未开通时，发送者将以原始 `open_id` 显示。
:::

## 接收模式

### HTTP Webhook（默认）

飞书将事件推送到你暴露的 HTTP 端点，驱动器会在可配置的端口上启动一个 aiohttp 服务器。

**准备工作**

1. 前往[飞书开放平台](https://open.feishu.cn)（或 [Lark 开发者平台](https://open.larksuite.com)）。
2. 创建一个**自建应用**，并在**权限管理**中开通上述权限范围。
3. 在**事件订阅**中开启 **im.message.receive_v1** 事件，并将请求 URL 设为 `http://your-host:8080/event`（与 `listen_port` 和 `listen_path` 配置一致）。
4. 复制 **App ID**、**App Secret**、**验证 Token** 和**加密 Key**（不需要加密可留空）。
5. 发布应用版本，并将机器人添加到目标群聊。

::: warning 需要公网可访问的地址
飞书需要从公网访问你的 HTTP 端点。请使用反向代理、内网穿透工具（如 ngrok）或将服务部署在公网服务器上。
:::

### 长连接 / WebSocket

驱动器向飞书服务器建立持久的出站 WebSocket 连接，无需暴露公网 HTTP 端点，适合本地或有防火墙的部署环境。

**准备工作**

1. 前往[飞书开放平台](https://open.feishu.cn)（或 [Lark 开发者平台](https://open.larksuite.com)）。
2. 创建一个**自建应用**，并在**权限管理**中开通上述权限范围。
3. 在**事件订阅**中开启 **im.message.receive_v1** 事件，并选择**"使用长连接接收事件"**，无需设置请求 URL。
4. 复制 **App ID** 和 **App Secret**。
5. 发布应用版本，并将机器人添加到目标群聊。
6. 在配置中设置 `use_long_connection: true`。

## 配置项

在 `config.json` 的 `feishu.<实例ID>` 下添加：

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `app_id` | 是 | — | 飞书/Lark App ID |
| `app_secret` | 是 | — | 飞书/Lark App Secret |
| `use_long_connection` | 否 | `false` | `true` = WebSocket 长连接；`false` = HTTP Webhook |
| `verification_token` | 否 | `""` | 事件验证 Token——仅 HTTP Webhook 模式使用 |
| `encrypt_key` | 否 | `""` | 事件加密 Key——仅 HTTP Webhook 模式使用（留空表示不加密） |
| `listen_port` | 否 | `8080` | 监听传入事件的 HTTP 端口——仅 HTTP Webhook 模式使用 |
| `listen_path` | 否 | `"/event"` | 监听传入事件的 HTTP 路径——仅 HTTP Webhook 模式使用 |

**HTTP Webhook 示例**

```json
{
  "feishu": {
    "fs_main": {
      "app_id": "cli_xxxxxxxxxxxx",
      "app_secret": "your_app_secret",
      "verification_token": "your_verification_token",
      "encrypt_key": "",
      "listen_port": 8080,
      "listen_path": "/event"
    }
  }
}
```

**长连接示例**

```json
{
  "feishu": {
    "fs_main": {
      "app_id": "cli_xxxxxxxxxxxx",
      "app_secret": "your_app_secret",
      "use_long_connection": true
    }
  }
}
```

## 规则频道键

在 `rules.json` 的 `channels` 或 `from`/`to` 下使用：

| 键 | 说明 |
|---|---|
| `chat_id` | 飞书开放 Chat ID，如 `"oc_xxxxxxxxxxxxxxxxxx"` |

```json
{
  "fs_main": { "chat_id": "oc_xxxxxxxxxxxxxxxxxx" }
}
```

Chat ID 可在飞书开发者后台查看，也可从机器人在该群收到的事件 payload 中获取。

## 注意事项

- 目前仅接收**文本消息**，其他消息类型（卡片、文件、表情）在接收端会被忽略。
- 发出的附件以 URL 形式附加到文本消息末尾（通过 API 上传文件需要额外权限，暂未实现）。
- 发送者显示名称和头像通过联系人 API（`contact:contact.base:readonly`）解析。未开通该权限时，发送者将以原始 `open_id` 显示。
