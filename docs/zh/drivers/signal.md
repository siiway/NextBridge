# Signal

Signal 驱动器通过连接一个运行中的 [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) 实例来收发消息，该实例负责处理底层的 Signal 协议。接收消息使用 WebSocket，发送消息使用 HTTP。

## 前置条件

你需要先运行一个 `signal-cli-rest-api` 实例。使用 Docker 最为简便：

```bash
docker run -d \
  --name signal-api \
  -p 8080:8080 \
  -v /path/to/signal-cli-config:/home/.local/share/signal-cli \
  bbernhard/signal-cli-rest-api
```

然后通过 API 的 `/v1/register` 或 `/v1/qrcodelink` 端点注册或关联你的 Signal 账号。详细步骤请参考 [signal-cli-rest-api 文档](https://bbernhard.github.io/signal-cli-rest-api/)。

## 配置项

在配置文件的 `signal.<实例ID>` 下添加：

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `api_url` | 是 | — | signal-cli-rest-api 实例的基础 URL，例如 `http://localhost:8080` |
| `number` | 是 | — | 已注册的 Signal 手机号，例如 `+12025551234` |
| `max_file_size` | 否 | `52428800`（50 MB） | 发送附件时单个文件的最大字节数 |

```json
{
  "signal": {
    "sg_main": {
      "api_url": "http://localhost:8080",
      "number": "+12025551234"
    }
  }
}
```

## 规则频道键

在 `rules.json` 的 `channels` 或 `from`/`to` 下使用：

| 键 | 说明 |
|---|---|
| `recipient` | 单聊时填对方手机号（如 `+12025551234`），群聊时填 `group.<base64id>` |

```json
{
  "sg_main": {
    "recipient": "+12025551234"
  }
}
```

群聊时，`recipient` 的值以 `group.` 开头，后跟 base64 编码的群组 ID。最简单的获取方式是向该群发一条消息，然后查看 NextBridge 日志中打印的 envelope 数据。

## 注意事项

- Bot 不会回显自身发出的消息（发送走纯 HTTP 路径，不经过 WebSocket）。
- 接收到的附件会立即从 signal-cli REST API 下载，无需下游平台访问你的 Signal 实例。
- 发送附件时，文件会以 base64 编码内联于 `/v2/send` 请求体中。
- WebSocket 断线后驱动器将每隔 5 秒自动重连。
