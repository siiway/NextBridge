> 本文档由 AI 编写，已经人工审核。

# Matrix

Matrix 驱动器通过长轮询同步循环（使用 [mautrix-python](https://github.com/mautrix/python)）接收消息，并通过 Matrix 客户端-服务器 API 向房间发送消息。

## 准备工作

1. 在你的 Homeserver（或 matrix.org 等公共服务器）上为 Bot 创建一个 Matrix 账号。
2. 记录完整的用户 ID（例如 `@mybot:matrix.org`）和 Homeserver URL（例如 `https://matrix.org`）。
3. 可以直接使用密码登录，也可以提前获取 access_token 并使用。
4. 将 Bot 账号邀请进每个需要桥接的房间。

## 配置项

在配置文件的 `matrix.<实例ID>` 下添加：

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `homeserver` | 是 | — | Homeserver URL，例如 `https://matrix.org` |
| `user_id` | 是 | — | 完整 Matrix 用户 ID，例如 `@mybot:matrix.org` |
| `password` | 否* | — | 登录密码 |
| `access_token` | 否* | — | 访问令牌（可替代 `password`） |
| `max_file_size` | 否 | `52428800`（50 MB） | 发送附件时单个文件的最大字节数 |
| `proxy` | 否 | — | 所有 Matrix API 请求的代理 URL（例如：`http://proxy.example.com:8080` 或 `socks5://proxy.example.com:1080`）。设置为 `null` 可显式禁用此实例的代理（忽略全局代理设置）。 |
| `enable_e2e` | 否 | `false` | 启用端到端加密支持。启用后，Bot 将自动加密发送到加密房间的消息，并解密接收到的消息。 |
| `store_path` | 否 | `data/e2e` | 存储加密密钥的路径（当 `enable_e2e` 为 `true` 时必需）。如果该目录不存在，将会自动创建。 |

> [!IMPORTANT]
> \* `password` 和 `access_token` 至少需要提供一个。
> \** 当 `enable_e2e` 为 `true` 时，`store_path` 为必填项。

```json
{
  "matrix": {
    "mx_main": {
      "homeserver": "https://matrix.org",
      "user_id": "@mybot:matrix.org",
      "password": "your_password",
      "max_file_size": 52428800
    }
  }
}
```

## 规则频道键

在 `rules.json` 的 `channels` 或 `from`/`to` 下使用：

| 键 | 说明 |
|---|---|
| `room_id` | Matrix 房间 ID，例如 `!abc123:matrix.org` |

```json
{
  "mx_main": {
    "room_id": "!abc123:matrix.org"
  }
}
```

## 注意事项

- Bot 会忽略自身发送的消息，防止消息回显循环。
- 从 Matrix 接收到的媒体文件会通过已认证的客户端直接下载，下游平台无需 Matrix 凭据。
- 发送媒体时，文件会先上传至 Homeserver 的媒体 API，再以原生 Matrix 媒体事件（`m.image`、`m.video`、`m.audio`、`m.file`）形式发出。
- 启动时自动跳过 Bot 上线前的历史消息，不会重复处理。
- 当 `enable_e2e` 设置为 `true` 时，支持端对端加密（E2E）。启用后，Bot 将自动加密发送到加密房间的消息，并解密接收到的消息。加密密钥存储在 `store_path` 指定的路径中。
