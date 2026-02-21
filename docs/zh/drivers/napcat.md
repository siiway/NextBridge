# NapCat（QQ）

NextBridge 通过 [NapCat](https://napneko.github.io) 连接 QQ——NapCat 是一个非官方 QQ 客户端，提供 OneBot 11 WebSocket API。由于 QQ 没有面向普通账号的官方机器人 API，NapCat 作为中间桥接层使用。

## 准备工作

1. 安装并运行 NapCat，将其配置为 WebSocket 服务端模式。
2. 记录 WebSocket 地址（默认：`ws://127.0.0.1:3001`）和你设置的访问令牌。
3. 在 `data/config.json` 中添加实例配置。

## 配置项

在 `config.json` 的 `napcat.<实例ID>` 下添加：

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `ws_url` | 否 | `ws://127.0.0.1:3001` | NapCat 服务端的 WebSocket 地址 |
| `ws_token` | 否 | — | 访问令牌（作为 `?access_token=…` 追加到 URL） |
| `max_file_size` | 否 | `10485760`（10 MB） | 发送附件时单个文件的最大下载字节数 |
| `cqface_mode` | 否 | `"gif"` | QQ 表情段的呈现方式。`"gif"` 将表情以动态 GIF 图上传（来自本地 `db/cqface-gif/` 数据库）；`"emoji"` 以内联文本呈现，如 `:cqface306:`。 |
| `file_send_mode` | 否 | `"stream"` | 向 QQ 上传文件和视频的方式。`"stream"` 使用分块 `upload_file_stream`（推荐用于大文件）；`"base64"` 将整个内容编码后直接传给 `upload_group_file`。 |
| `stream_threshold` | 否 | `0`（禁用） | 大于 0 时，当文件或视频超过该字节数时自动切换为 `"stream"` 模式，忽略 `file_send_mode` 的设置。 |

```json
{
  "napcat": {
    "qq_main": {
      "ws_url": "ws://127.0.0.1:3001",
      "ws_token": "your_secret",
      "max_file_size": 10485760
    }
  }
}
```

## 规则频道键

在 `rules.json` 的 `channels` 或 `from`/`to` 下使用：

| 键 | 说明 |
|---|---|
| `group_id` | QQ 群号（字符串或数字均可） |

```json
{
  "qq_main": { "group_id": "947429526" }
}
```

::: info 仅支持群消息
NextBridge 目前只桥接**群消息**，不转发私聊消息。
:::

## 消息段解析

收到的消息依据 OneBot 11 消息段数组解析：

| 段类型 | 处理方式 |
|---|---|
| `text` | 转为消息文本 |
| `at` | 转为 `@名称` 格式的文本 |
| `image` | 作为 `image` 附件转发 |
| `record` | 作为 `voice` 附件转发 |
| `video` | 作为 `video` 附件转发 |
| `file` | 作为 `file` 附件转发 |
| 其他（表情、回复、合并转发…） | 静默跳过 |

## 发送

| 附件类型 | 发送方式 |
|---|---|
| `image` | 下载后以 base64 编码发送（`base64://…`） |
| `voice` | 下载后以 base64 编码发送（`base64://…`） |
| `video` | 下载后按 `file_send_mode` 发送（stream 或 base64） |
| `file` | 下载后按 `file_send_mode` 发送（stream 或 base64） |

`file_send_mode` 和 `stream_threshold` 配置项控制视频和文件的上传方式。Stream 模式（`upload_file_stream` → `upload_group_file`）为默认值，对大文件更可靠。如果你的 NapCat 版本不支持流式上传，可改为 `"base64"`；配置 `stream_threshold` 可在文件超过指定大小时自动回退到 stream 模式。

## 注意事项

- **自身消息回显**：NapCat 会将机器人自己发送的消息作为真实事件回传。NextBridge 通过对比 `user_id` 与 `self_id` 自动过滤这类消息。
- **自动重连**：WebSocket 连接断开后，NextBridge 每隔 5 秒自动重新连接。
