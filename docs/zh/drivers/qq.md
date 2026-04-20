> 本文档由 AI 编写，已经人工审核。

# QQ 驱动器

NextBridge 通过一个统一的 QQ 驱动器连接 QQ，并支持三种协议模式：

## 支持的协议模式

| 模式           | 说明                                                                           | 官网 / 文档                                    | 仓库                                                    |
| -------------- | ------------------------------------------------------------------------------ | ---------------------------------------------- | ------------------------------------------------------- |
| `napcat`       | 功能完整的 WebSocket 模式，支持 `upload_file_stream`                           | [napneko.github.io](https://napneko.github.io) | [NapNeko/NapCatQQ](https://github.com/NapNeko/NapCatQQ) |
| `lagrange`     | 通过 WebSocket 运行的 OneBot 11，使用协议兼容的 API 和基于本地路径的群文件上传 | https://lagrangedev.github.io/Lagrange.Doc/v1/ | https://github.com/LagrangeDev/Lagrange.OneBot          |
| *`onebot_v11`* | *面向暴露标准 OneBot 11 API 的通用实现*                                        | https://11.onebot.dev                          | https://github.com/botuniverse/onebot-11                |

## 准备工作

1. 安装并运行你选择的 QQ 机器人服务端（NapCat、Lagrange 或其他 OneBot 11 实现），并配置为 WebSocket 服务端模式。
2. 记录 WebSocket 地址（常见为 `ws://127.0.0.1:3001`）和访问令牌（如有）。
3. 在 `config.json` 的 `qq.<实例ID>` 下添加实例，并设置 `protocol`。

## 配置

在 `config.json` 的 `qq.<实例ID>` 下添加：

| 键                                 | 是否必填 | 默认值                | 说明                                                                                                                                                             |
| ---------------------------------- | -------- | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `protocol`                         | 否       | `napcat`              | 协议模式：`napcat`、`lagrange` 或 `onebot_v11`                                                                                                                   |
| `ws_url`                           | 否       | `ws://127.0.0.1:3001` | QQ 机器人服务端的 WebSocket 地址                                                                                                                                 |
| `ws_token`                         | 否       | —                     | 访问令牌（作为 `?access_token=...` 追加到 URL）                                                                                                                  |
| `ws_ssl_verify`                    | 否       | `true`                | `wss://` WebSocket 是否校验证书。仅当机器人服务端使用自签名/私有 CA 证书时再设为 `false`。                                                                       |
| `max_file_size`                    | 否       | `10485760`（10 MB）   | 发送附件时单个文件的最大下载字节数                                                                                                                               |
| `cqface_mode`                      | 否       | `"gif"`               | QQ 表情段的呈现方式。`"gif"` 将表情以动态图上传（来自本地 `db/cqface-gif/` 数据库）；`"emoji"` 以内联文本呈现，如 `:cqface306:`。                                |
| `file_send_mode`                   | 否       | `"stream"`            | NapCat 使用的上传模式。`"stream"` 使用 `upload_file_stream`；`"base64"` 直接发送 `base64://...`。Lagrange 和通用 OneBot 模式会回退为基于本地临时路径的文件上传。 |
| `stream_threshold`                 | 否       | `0`（禁用）           | 大于 0 时，在 NapCat 模式下当文件超过该字节数会自动切换为 `stream` 模式，忽略 `file_send_mode`。                                                                 |
| `forward_render_enabled`           | 否       | `false`               | 启用合并转发渲染为 HTML 页面。仅 `napcat` 和 `lagrange` 模式支持。                                                                                               |
| `forward_render_ttl_seconds`       | 否       | `15552000`（180 天）  | 合并转发 HTML 页面有效期（秒）。最小值为 60 秒。                                                                                                                 |
| `forward_render_mount_path`        | 否       | `"/qq-forward"`       | 合并转发页面在共享 HTTP 服务中的挂载路径。默认会自动变成 `"/qq-forward/<instance_id>"`。                                                                         |
| `forward_render_persist_enabled`   | 否       | `false`               | 是否将合并转发页面持久化到数据库。开启后，重启后仍可通过链接访问。                                                                                               |
| `forward_render_image_method`      | 否       | `"url"`               | 合并转发页面中图片的渲染方式。`"url"`：图片二进制写入数据库并通过桥接服务 URL 提供；`"base64"`：直接把 data URI 内嵌到页面中。                                   |
| `forward_render_base_url`          | 否       | `""`                  | 合并转发链接优先使用的公开前缀。设置后，链接会生成成 `${forward_render_base_url}/{page_id}`。                                                                    |
| `forward_render_asset_ttl_seconds` | 否       | `1209600`（14 天）    | 桥接服务上合并转发图片资源的有效期（秒）。设为 `0` 表示永久有效。                                                                                                |
| `forward_render_cqface_gif`        | 否       | `true`                | 合并转发 HTML 中 `face` 段的渲染策略。                                                                                                                           |
| `proxy`                            | 否       | —                     | WebSocket 连接和媒体下载使用的代理 URL。设为 `null` 可显式禁用本实例的代理。                                                                                     |

合并转发链接基础地址优先级：
1. `forward_render_base_url`（不自动拼接 mount path）
2. `global.base_url`（自动拼接 mount path）
3. 根据 `global.http` 的 host/port 推导

```json
{
  "qq": {
    "qq_main": {
      "protocol": "lagrange",
      "ws_url": "ws://127.0.0.1:3001",
      "ws_token": "your_secret"
    }
  }
}
```

## 规则地址

在 `rules.json` 的 `channels` 或 `from`/`to` 中使用：

| 键         | 说明                        |
| ---------- | --------------------------- |
| `group_id` | QQ 群号（字符串或数字均可） |

```json
{
  "qq_main": { "group_id": "947429526" }
}
```

::: info 仅支持群消息
NextBridge 目前只桥接**群消息**，不转发私聊消息。
:::

## 按协议表现

| 功能                 | napcat | lagrange | onebot_v11 |
| -------------------- | ------ | -------- | ---------- |
| 消息收发             | 支持   | 支持     | 支持       |
| 合并转发渲染         | 支持   | 支持     | 不支持     |
| `upload_file_stream` | 支持   | 不支持   | 不支持     |
| 群文件上传           | 支持   | 支持     | 尽力支持   |
| 群文件链接查询       | 支持   | 支持     | 尽力支持   |

## 消息段解析

收到的消息依据 OneBot 11 消息段数组解析：

| 段类型                              | 处理方式                                                                                                                                                  |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `text`                              | 转为消息文本                                                                                                                                              |
| `at`                                | 转为 `@名称` 格式的文本                                                                                                                                   |
| `image`                             | 作为 `image` 附件转发；在合并转发中：按 `forward_render_image_method`（`url`/`base64`）渲染                                                               |
| `record`                            | 作为 `voice` 附件转发；在合并转发中：尽量嵌入为可播放音频，AMR 可在可用时转码为 OGG                                                                       |
| `video`                             | 作为 `video` 附件转发；在合并转发中：嵌入 `<video controls>` 播放器                                                                                       |
| `file`                              | 作为 `file` 附件转发；在 `napcat` 模式下走流式上传，其余模式会先写入本地临时路径，再通过 `upload_group_file` 发送（最好确保机器人能访问同一文件系统路径） |
| `forward`                           | 调用 `get_forward_msg` 拉取节点，渲染为临时 HTML 页面并转发链接；嵌套合并转发会递归渲染                                                                   |
| `face`                              | 根据 `cqface_mode` 选择本地 cqface GIF 数据库或内联文本                                                                                                   |
| 其他（`reply`、`json`、`mface` 等） | 尽量解析；不支持的类型会被跳过或回退为文本提示                                                                                                            |

合并转发图片行为：
- `url` 模式下，点击图片会打开桥接服务提供的缓存资源地址（`/asset/...`），不再直接跳转 QQ 原始 CDN。
- `base64` 模式下，图片会以内嵌方式渲染并由浏览器直接打开。

合并转发渲染安全策略：
- 内嵌图片 MIME 仅允许安全白名单（`JPEG/PNG/GIF/WebP/BMP/AVIF`）。
- 不安全 MIME（例如 `text/html`、`image/svg+xml`）会阻止内嵌，仅保留占位提示链接。

发送者 UID 可靠性提示：
- 当合并转发中的发送者 UID 无法可靠校验（包括某些单发送者场景）时，页面会标记 `UID 不可信`。
- 即使标记不可信，页面仍会展示 QQ 号以便人工核对。

::: info 合并转发页面访问控制
合并转发链接为普通路径，且每个页面有独立 TTL。到期后当前页面会原地切换为“已销毁”状态。若启用持久化存储，重启后页面仍可再次访问。
:::

::: info 按规则覆盖合并转发 TTL
可在规则中通过 `msg.forward_render_ttl_seconds` 覆盖合并转发页面有效期（最小 60 秒）。对于 `connect` 规则，`channels.<instance>.msg.forward_render_ttl_seconds` 优先级高于规则级 `msg.forward_render_ttl_seconds`。
:::

::: info 合并转发表情 GIF Host
当 `forward_render_cqface_gif=true`（默认）时，NextBridge 使用：

- `https://nextbridge.siiway.org/db/cqface-gif/`

你也可以把 `forward_render_cqface_gif` 设置为字符串来指定自定义 Host，例如：

- `https://nb-res-cn.siiway.top/cqface-gif/`

NextBridge 不会在多个 Host 之间自动回退。
:::

## 发送

| 附件类型 | 发送方式                                                                                                      |
| -------- | ------------------------------------------------------------------------------------------------------------- |
| `image`  | 下载后以 base64 编码发送（`base64://...`）                                                                    |
| `voice`  | 下载后以 base64 编码发送（`base64://...`）                                                                    |
| `video`  | `napcat` 模式按 `file_send_mode`（`stream`/`base64`）发送；`lagrange`/`onebot_v11` 模式按本地路径上传尽力发送 |
| `file`   | `napcat` 模式按 `file_send_mode`（`stream`/`base64`）发送；`lagrange`/`onebot_v11` 模式按本地路径上传尽力发送 |

语音兼容性：桥接到其他平台时，如果识别到 QQ 语音为 AMR（如 `.amr`），NextBridge 会优先尝试转码为 `audio/ogg`（Opus）再发送，以提升 Discord 等平台兼容性。若转码失败，会自动回退为原始音频。

::: tip ffmpeg 依赖
AMR 转码依赖系统中的 `ffmpeg` 可执行文件。未安装 ffmpeg 时语音仍可转发，但会跳过 AMR -> OGG 转换。
:::

`file_send_mode` 与 `stream_threshold` 主要影响 `napcat` 模式。默认 Stream 模式（`upload_file_stream` -> `upload_group_file`）通常对大文件更可靠；若你的实现不支持流式上传，可改用 `base64`。

## 注意事项

- 自身消息回显：部分 QQ 机器人服务端会把机器人自己发送的消息回传为入站事件。NextBridge 会通过比较 `user_id` 与 `self_id` 自动过滤。
- 自动重连：WebSocket 连接断开后，NextBridge 会每 5 秒自动重连。
- TLS 证书：若 `wss://` 连接报 `CERTIFICATE_VERIFY_FAILED` 且部署使用自签名/内网 CA 证书，可在该 QQ 实例将 `ws_ssl_verify` 设为 `false`。
