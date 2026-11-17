# QQ

NextBridge 通过 OneBot 11 WebSocket 协议连接 QQ。支持多种协议后端：[NapCat](https://napneko.github.io)（默认）、[Lagrange.OneBot](https://github.com/LagrangeDev/Lagrange.Core)，以及任何通用 OneBot 11 实现。

## 准备工作

1. 安装并运行你选择的 OneBot 11 后端（如 NapCat），将其配置为 WebSocket 服务端模式。
2. 记录 WebSocket 地址（默认：`ws://127.0.0.1:3001`）和你设置的访问令牌。
3. 在 `data/config.json` 中添加实例配置。

## 配置项

在 `config.json` 的 `qq.<实例ID>` 下添加：

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `protocol` | 否 | `"napcat"` | OneBot 11 后端协议：`"napcat"`、`"lagrange"` 或 `"onebot_v11"`。控制哪些协议特定功能可用（合并转发 API、流式上传等） |
| `connection_mode` | 否 | `"forward"` | WebSocket 连接方向：`"forward"` 由 NextBridge 连接 NapCat 的 WebSocket 服务端；`"reverse"` 由 NapCat 主动连接 NextBridge 提供的 WebSocket 服务端。 |
| `ws_url` | 否 | `ws://127.0.0.1:3001` | `connection_mode: "forward"` 时 NapCat WebSocket 服务端的地址 |
| `ws_token` | 否 | — | OneBot 访问令牌。正向模式会以 `access_token` 查询参数发送；反向模式要求 NapCat 使用 `Authorization: Bearer <token>` 连接。 |
| `reverse_ws_path` | 否 | `/onebot/v11/<实例ID>` | `connection_mode: "reverse"` 时 NextBridge 提供的 WebSocket 路径。 |
| `ws_ssl_verify` | 否 | `true` | WSS 连接是否验证 TLS 证书。自签名证书请设为 `false` |
| `max_file_size` | 否 | `10485760`（10 MB） | 发送附件时单个文件的最大下载字节数 |
| `cqface_mode` | 否 | `"gif"` | QQ 表情段的呈现方式。`"gif"` 将表情以动态 GIF 图上传（优先取自本地表情库；本地缺失时回退到 `cqface_gif_host` 配置的远程主机下载，见[表情 GIF 资源](#表情-gif-资源)）；`"emoji"` 以内联文本呈现，如 `:cqface306:`。 |
| `file_send_mode` | 否 | `"stream"` | 向 QQ 上传文件和视频的方式。`"stream"` 使用分块 `upload_file_stream`（推荐用于大文件）；`"base64"` 将整个内容编码后直接传给 `upload_group_file`。 |
| `stream_threshold` | 否 | `0`（禁用） | 大于 0 时，当文件或视频超过该字节数时自动切换为 `"stream"` 模式，忽略 `file_send_mode` 的设置。 |
| `forward_render_enabled` | 否 | `false` | 启用 QQ 合并转发消息渲染为 HTML 页面 |
| `forward_render_ttl_seconds` | 否 | `15552000`（180 天） | 渲染的合并转发页面存活时间（秒） |
| `forward_render_mount_path` | 否 | `"/qq-forward"` | 合并转发页面的 HTTP 挂载路径 |
| `forward_render_persist_enabled` | 否 | `false` | 将合并转发页面持久化到数据库，重启后仍可访问 |
| `forward_render_image_method` | 否 | `"url"` | 合并转发页面的图片渲染方式：`"url"`（通过数据库+桥接 URL 提供）或 `"base64"`（内联 data URI） |
| `forward_render_asset_ttl_seconds` | 否 | `1209600`（14 天） | 合并转发页面缓存图片/资源的 TTL |
| `forward_render_base_url` | 否 | — | 合并转发页面链接的自定义公共 URL 前缀。设置后链接格式为 `{base_url}/{page_id}`（不会自动追加挂载路径） |
| `cqface_gif_host` | 否 | `true` | 表情 GIF 主机。既用于合并转发 HTML 页面中的 `<img>` 来源，也作为主消息路径下本地表情库缺失时的远程回退。`false` 完全禁用远程主机（合并转发回退为 unicode 表情，主路径缺失的表情直接丢弃）、`true` 使用默认主机 `https://cqface.p.wyf9.top/dist/`、字符串则自定义基础 URL。 |
| `edit_via_reply` | 否 | `true` | 当其他平台编辑了已桥接的消息时，通过发送一条引用原始消息并添加 `edit_prefix` 前缀的新消息来在 QQ 上模拟编辑。设为 `false` 可完全忽略收到的编辑。 |
| `edit_prefix` | 否 | `"[编辑]"` | 添加到模拟编辑消息前的前缀，用于与普通消息区分。仅在 `edit_via_reply` 为 `true` 时生效。 |
| `enable_recall` | 否 | `true` | 是否同步消息撤回。启用后，QQ 上的撤回会被检测并桥接到其他平台，其他平台的撤回也会通过原生 `delete_msg` API 应用到 QQ。设为 `false` 可完全禁用撤回同步。 |
| `proxy` | 否 | — | 用于 WebSocket 连接和附件下载的代理 URL（例如：`http://proxy.example.com:8080` 或 `socks5://proxy.example.com:1080`）。设置为 `null` 可显式禁用此实例的代理（忽略全局代理设置）。 |
| `media_proxy` | 否 | — | 仅用于获取媒体/附件的代理 URL。未设置时默认跟随 `proxy`。 |

```json
{
  "qq": {
    "qq_main": {
      "protocol": "napcat",
      "ws_url": "ws://127.0.0.1:3001",
      "ws_token": "your_secret",
      "max_file_size": 10485760
    }
  }
}
```

## 反向 WebSocket 连接

将 `connection_mode` 设为 `"reverse"` 后，NextBridge 会在共享 HTTP 服务上提供 WebSocket 端点；NapCat 应在「网络配置」中新建 **WebSocket 客户端**并连接到该地址。例如实例 ID 为 `qq_main`、HTTP 服务监听 `9080` 时，地址为 `ws://<NextBridge主机>:9080/onebot/v11/qq_main`。可用 `reverse_ws_path` 自定义路径。

若配置了 `ws_token`，必须在 NapCat 的反向 WebSocket 配置中使用相同 token；NextBridge 会验证 `Authorization: Bearer <token>`，避免未授权客户端控制机器人。每个实例同一时间只接受一个反向连接。

## 规则频道键

在 `rules.json` 的 `channels` 或 `from`/`to` 下使用：

| 键 | 说明 |
|---|---|
| `group_id` | QQ 群号（字符串或数字均可） |
| `user_id` | QQ 用户 ID，用于私聊消息（字符串或数字均可） |

```json
{
  "qq_main": { "group_id": "947429526" }
}
```

::: info 群消息与私聊消息
NextBridge 默认桥接**群消息**。通过指定 `user_id`（而非 `group_id`）也可以桥接私聊消息。`/nb bind` 指令可在私聊中使用。
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
| `face` | 依据 `cqface_mode`：`"gif"` 时作为 `image` 附件转发，优先取本地库，本地缺失则从配置的表情 GIF 主机下载（两者都失败才丢弃该段）；`"emoji"` 时转为 `:cqfaceNNN:` 内联文本 |
| 其他（回复、合并转发...） | 静默跳过 |

## 发送

| 附件类型 | 发送方式 |
|---|---|
| `image` | 下载后以 base64 编码发送（`base64://...`） |
| `voice` | 下载后以 base64 编码发送（`base64://...`） |
| `video` | 下载后按 `file_send_mode` 发送（stream 或 base64） |
| `file` | 下载后按 `file_send_mode` 发送（stream 或 base64） |

`file_send_mode` 和 `stream_threshold` 配置项控制视频和文件的上传方式。Stream 模式（`upload_file_stream` → `upload_group_file`）为默认值，对大文件更可靠。如果你的 OneBot 后端不支持流式上传，可改为 `"base64"`；配置 `stream_threshold` 可在文件超过指定大小时自动回退到 stream 模式。

## 合并转发渲染

当 `forward_render_enabled` 为 `true` 时，QQ 合并转发消息会被渲染为独立的 HTML 页面，支持完整的媒体内容（图片、语音、视频、文件）。渲染页面可通过 HTTP 服务器在配置的 `forward_render_mount_path` 路径访问。

- **页面销毁**：合并转发页面在销毁或过期后会直接失效，刷新时会返回 404，不会再次打开旧页面。
- **页面设置**：合并转发页面右上角提供设置入口，可切换颜色模式与合并转发显示方式，并使用 LocalStorage 记忆。
- **不可靠 UID 标记**：当 OneBot 后端在同一批合并转发中无法可靠对应发送者 ID 时，页面会把该 UID 标记为不可靠。
- **按规则覆盖 TTL**：`forward_render_ttl_seconds` 可通过规则中的 `msg` 配置按规则覆盖。

## 表情 GIF 资源

表情 GIF **不随 NextBridge 打包**。开启 `cqface_mode: "gif"` 时，表情段会先在本地表情库中查找，只有缺失时才下载：

1. `<data>/cqface-gif/<id>.gif`（同步下来的副本，通常用这个）
2. 源码目录里的 `db/cqface-gif/<id>.gif`（如果你还留着的话）
3. `<cqface_gif_host><id>.gif`，即远程主机

想要完整的本地副本（离线使用或自建部署），把它同步到数据目录即可：

```sh
uv run scripts/sync_cqface.py
# 或指定其它数据目录 / 镜像
uv run scripts/sync_cqface.py --dest /srv/nextbridge/data/cqface-gif
```

脚本会下载 [wyf9/cqface](https://github.com/wyf9/cqface) 的归档，并把其中的 `dist/*.gif` 写入目标目录；已存在的文件默认跳过，加 `--force` 才覆盖，因此手工补充的表情不会被覆盖。

## 消息编辑同步

QQ（OneBot 11）**没有原生的「编辑消息」API**，因此其他平台（Discord/Telegram）上的编辑无法就地应用到 QQ 上的原始消息。NextBridge 转而**模拟**编辑：

- 当编辑被桥接到 QQ 时，NextBridge 会发送一条**新消息**，该消息**引用（回复）**原始桥接消息，并在前面添加 `edit_prefix` 前缀（默认 `[编辑]`）。
- 重复编辑始终引用**原始**桥接消息，因此编辑始终锚定在原消息上。
- 每条模拟编辑消息都会保存消息映射，因此后续对该 `[编辑]` 消息的编辑、撤回或回复可继续参与桥接路由。
- 仅同步文本内容，编辑时不会重新发送附件。
- 将 `edit_via_reply` 设为 `false` 可关闭此行为并忽略收到的编辑。

## 消息撤回同步

QQ（OneBot 11）**原生支持消息撤回**，因此撤回可以双向同步：

- **检测**：QQ 端撤回消息时，OneBot 后端会推送 `group_recall`（群聊）或 `friend_recall`（私聊）通知事件，NextBridge 据此将撤回桥接到其他平台。
- **应用**：其他平台（Discord/Telegram）上的撤回会通过原生 `delete_msg` API 应用到 QQ 上对应的桥接消息。
- 若一条源消息被拆分成多条 QQ 消息，撤回时会一并删除全部对应消息。
- 将 `enable_recall` 设为 `false` 可完全禁用撤回的检测与应用。

## 注意事项

- **自身消息回显**：OneBot 后端会将机器人自己发送的消息作为真实事件回传。NextBridge 通过对比 `user_id` 与 `self_id` 自动过滤这类消息。
- **自动重连**：WebSocket 连接断开后，NextBridge 每隔 5 秒自动重新连接。
