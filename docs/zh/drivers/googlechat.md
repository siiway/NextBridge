# Google Chat

Google Chat 驱动器通过**服务账号**和 **Google Chat REST API** 将 Google Chat 空间与其他平台桥接。它启动一个 HTTP 服务器接收 Google 推送的消息事件，并通过 Chat API 发送回复。

## 前置条件

::: tip
你需要一个 **Google Workspace** 账号来进行配置，否则你会遇到
![Google Chat API is only available to Google Workspace users](https://images.krnl64.win/api/get/6efb709e-7dd7-4183-9e25-225004f5695e.png)
:::

1. 在 [console.cloud.google.com](https://console.cloud.google.com/) **创建 Google Cloud 项目**（或使用已有项目）。
2. **启用 Google Chat API**：进入 *API 和服务 → 库*，搜索"Google Chat API"并启用。
3. **创建服务账号**：进入 *IAM 和管理 → 服务账号*，创建新账号并下载 JSON 密钥文件。
4. **配置 Chat 应用**：进入 *API 和服务 → Google Chat API → 配置* 并填写：
   - **应用名称**、**头像 URL**、**描述**（必填字段）
   - 在 **连接设置** 下选择 **HTTP 端点 URL** 并填入机器人的公开地址，例如 `https://example.com/google-chat/events`。
   - 在 **可见性** 下选择可安装该机器人的用户或群组。
5. **将机器人添加到空间**：在 Google Chat 中创建或打开一个空间，点击 *添加用户和应用*，按名称添加机器人。

> HTTP 端点必须通过 HTTPS 公开可访问。开发阶段可使用 nginx/Caddy 反向代理或 ngrok 隧道工具。

## 配置项

在 `config.json` 中 `googlechat.<instance_id>` 下添加：

| 键 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `service_account_file` | 是* | — | 服务账号 JSON 密钥文件路径 |
| `service_account_json` | 是* | — | 内联服务账号 JSON 字符串（与文件路径二选一） |
| `listen_port` | 否 | `8090` | 驱动器监听的 HTTP 端口 |
| `listen_path` | 否 | `"/google-chat/events"` | 事件端点的 HTTP 路径 |
| `endpoint_url` | 否 | — | 端点的完整公开 URL（设置后启用请求签名验证） |
| `max_file_size` | 否 | `52428800`（50 MB）| 附件大小上限（字节） |

\* `service_account_file` 与 `service_account_json` 必须填写其中一个。

### 使用文件路径

```json
{
  "googlechat": {
    "my_space": {
      "service_account_file": "/secrets/google-chat-sa.json",
      "listen_port": 8090,
      "endpoint_url": "https://example.com/google-chat/events"
    }
  }
}
```

### 内联 JSON（适用于密钥管理器）

```json
{
  "googlechat": {
    "my_space": {
      "service_account_json": "{\"type\":\"service_account\",\"project_id\":\"...\", ...}"
    }
  }
}
```

## 规则通道键

| 键 | 说明 |
|---|---|
| `space_name` | Google Chat 空间资源名称，例如 `"spaces/AAAA"` |

`space_name` 存在于每条接收到的事件中。也可通过 Chat API 查询，或在 Google Cloud Console 的空间对象 `name` 字段中找到。

```json
{
  "my_space": {
    "space_name": "spaces/AAAAAbCdEfG"
  }
}
```

## 工作原理

**接收：** 当用户向机器人发送消息时，Google Chat 将 JSON 事件 POST 到配置的端点。驱动器会：
- 立即返回 `{"text": ""}` 以确认事件（Google 要求）
- 忽略非 `MESSAGE` 事件类型（`ADDED_TO_SPACE`、`REMOVED_FROM_SPACE` 等）
- 跳过机器人（包括自身）发送的消息
- 优先使用 `argumentText`（@提及后的文本），回退到完整 `text` 字段
- 使用服务账号令牌下载内联附件并转发给桥接核心

**发送：** 对于每条出站消息，驱动器会：
1. 获取（或刷新）服务账号 OAuth2 访问令牌
2. 向 `https://chat.googleapis.com/v1/{space_name}/messages` POST 消息
3. 对于拥有公开 HTTPS URL 的图片，发送带有图片小部件的 Card v2
4. 对于其他附件（或没有公开 URL 的图片），发送文本标签 `[类型: 文件名]`

## 请求验证

设置 `endpoint_url` 后，驱动器会对每条传入请求验证 Google 签名的 OIDC 令牌：
- 检查 `Authorization: Bearer <token>` 请求头
- 使用 Google 公钥验证令牌签名
- 确认受众（audience）与 `endpoint_url` 匹配
- 确认发送者邮箱为 `chat@system.gserviceaccount.com`

若未设置 `endpoint_url`，则跳过验证（适用于开发环境或防火墙后的部署）。

## 注意事项

- 服务账号必须在同一项目中启用 **Chat API**；无需任何 IAM 角色。
- Google Chat 要求有效的 HTTPS 端点，Chat 配置界面会拒绝纯 HTTP 地址。
- 仅当附件已有公开 URL 时，图片才会以 Card v2 小部件发送。来自其他平台（如 NapCat）的二进制附件将显示为文本标签，因为 Google Chat REST API 不支持在不借助 Drive/存储服务的情况下直接上传二进制文件。
- `rich_header` 前缀使用 Google Chat 有限的 Markdown 语法：`*粗体*` 和 `_斜体_`。
- Google Chat 支持空间、私信和群聊。请使用对应会话的 `space_name`。
