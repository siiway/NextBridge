> 本文档由 AI 编写，已经人工审核。

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
| `ws_token` | 否 | — | 访问令牌（作为 `?access_token=...` 追加到 URL） |
| `max_file_size` | 否 | `10485760`（10 MB） | 发送附件时单个文件的最大下载字节数 |
| `cqface_mode` | 否 | `"gif"` | QQ 表情段的呈现方式。`"gif"` 将表情以动态 GIF 图上传（来自本地 `db/cqface-gif/` 数据库）；`"emoji"` 以内联文本呈现，如 `:cqface306:`。 |
| `file_send_mode` | 否 | `"stream"` | 向 QQ 上传文件和视频的方式。`"stream"` 使用分块 `upload_file_stream`（推荐用于大文件）；`"base64"` 将整个内容编码后直接传给 `upload_group_file`。 |
| `stream_threshold` | 否 | `0`（禁用） | 大于 0 时，当文件或视频超过该字节数时自动切换为 `"stream"` 模式，忽略 `file_send_mode` 的设置。 |
| `forward_render_enabled` | 否 | `false` | 是否启用“QQ 合并转发消息”渲染。启用后会把合并转发内容渲染为临时 HTML 页面并转发链接。 |
| `forward_render_ttl_seconds` | 否 | `86400` | 合并转发 HTML 页面有效期（秒）。页面会在到期后于当前页直接切换为“已销毁”。最小值为 60 秒。 |
| `forward_render_mount_path` | 否 | `"/napcat-forward"` | 合并转发页面在共享 HTTP 服务中的挂载路径。使用默认值时，实际会按实例自动变为 `"/napcat-forward/<instance_id>"`，避免多实例冲突。 |
| `forward_render_persist_enabled` | 否 | `false` | 是否启用合并转发聊天记录持久化存储。开启后，页面内容会额外写入数据库，重启后仍可通过链接访问。 |
| `forward_assets_base_url` | 否 | `""` | 合并转发链接的公开基础地址（例如反代后的公网地址）。为空时自动使用 `global.http` 拼接本地地址。 |
| `proxy` | 否 | — | 用于 WebSocket 连接和附件下载的代理 URL（例如：`http://proxy.example.com:8080` 或 `socks5://proxy.example.com:1080`）。如果未设置，将使用全局代理配置（如有）。设置为 `null` 可显式禁用此实例的代理（忽略全局代理设置）。 |

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
| `forward`（合并转发） | 调用 `get_forward_msg` 拉取节点，渲染为临时 HTML 页面并转发链接；嵌套合并转发会递归渲染；语音会尽量嵌入为可播放音频，AMR 可在可用时转码为 OGG；文件段会显示名称/大小/file_id 元信息并尽量解析下载链接 |
| 其他（表情...） | 静默跳过；回复段只显示通用的“回复消息”提示 |

::: info 合并转发页面访问控制
合并转发链接包含一个短 token（查询参数 `t`），并且页面有独立有效期。页面到期后不会立刻跳走，而是会在原页动态切换成“已销毁”。如果启用了持久化存储，页面内容还可以在重启后继续访问。
:::

::: info 合并转发表情 GIF Host
当 `forward_render_cqface_gif=true`（默认）时，NextBridge 使用默认 GIF Host：

- `https://nextbridge.siiway.org/db/cqface-gif/`

如果你想手动切换到大陆加速源，可以把 `forward_render_cqface_gif` 设为字符串，例如：

- `https://nb-res-cn.siiway.top/cqface-gif/`

这两个地址都是可选配置，代码里不会自动互相回退。
:::

## 发送

| 附件类型 | 发送方式 |
|---|---|
| `image` | 下载后以 base64 编码发送（`base64://...`） |
| `voice` | 下载后以 base64 编码发送（`base64://...`） |
| `video` | 下载后按 `file_send_mode` 发送（stream 或 base64） |
| `file` | 下载后按 `file_send_mode` 发送（stream 或 base64） |

语音兼容性：当桥接到其他平台时，若检测到 QQ 语音为 AMR（例如 `.amr`），NextBridge 会优先尝试转码为 `audio/ogg`（Opus）后再发送，以提高 Discord 等平台的可识别性。若转码失败，则自动回退为原始音频继续转发。

::: tip ffmpeg 依赖
AMR 转码依赖系统中的 `ffmpeg` 可执行文件。若未安装 ffmpeg，语音仍会转发，但不会进行 AMR→OGG 转换。
:::

`file_send_mode` 和 `stream_threshold` 配置项控制视频和文件的上传方式。Stream 模式（`upload_file_stream` → `upload_group_file`）为默认值，对大文件更可靠。如果你的 NapCat 版本不支持流式上传，可改为 `"base64"`；配置 `stream_threshold` 可在文件超过指定大小时自动回退到 stream 模式。

## 注意事项

- **自身消息回显**：NapCat 会将机器人自己发送的消息作为真实事件回传。NextBridge 通过对比 `user_id` 与 `self_id` 自动过滤这类消息。
- **自动重连**：WebSocket 连接断开后，NextBridge 每隔 5 秒自动重新连接。
