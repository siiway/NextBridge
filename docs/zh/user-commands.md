> 本文档由 AI 编写，已经人工审核。

# 用户指令

NextBridge 支持多个内置指令，用户可以直接在聊天平台中输入这些指令来管理自己的身份和跨平台体验。

> **说明：** 内置指令位于 `nb` 命名空间下，例如 `/nb bind` 和 `/nb bind confirm`。该 `nb` 前缀可通过全局 `command_prefix` 选项自定义——修改后请相应替换 `nb`。

## `/nb bind`

管理跨平台账号绑定，用于 @mention 跨平台路由。

默认情况下，NextBridge 尝试通过匹配 **显示名称** 来映射跨平台的提及（Mention）。账号绑定允许您显式地链接您在不同平台上的 ID，从而确保提及始终指向正确的账号。

| 命令 | 说明 |
|---|---|
| `/nb bind setup` | 生成 6 位绑定码（5 分钟有效） |
| `/nb bind confirm <code>` | 在另一个平台上确认绑定码 |
| `/nb bind rm [instance_id]` | 移除特定绑定或全部绑定 |
| `/nb bind list` | 列出所有已绑定的账号 |

### 示例

1. 在 **平台 A**（如 Discord）上输入 `/nb bind setup`——NextBridge 将回复一个唯一的 6 位数字验证码（例如 `123456`）。
2. 在 **平台 B**（如 QQ）上输入 `/nb bind confirm 123456`。
3. 账号绑定完成：在任一平台上提及您时，都会解析为您在其他平台绑定的账号。

## `/nb notify`

控制哪些绑定的平台接收 @mention 通知。

> **配置开关**：`global.mention_notify_control`（默认 `true`）。设为 `false` 可全局禁用此功能。

| 命令 | 说明 |
|---|---|
| `/nb notify mode all` | 所有绑定的平台都接收 @通知（默认） |
| `/nb notify mode whitelist` | 仅白名单中的平台接收通知 |
| `/nb notify mode blacklist` | 除黑名单外的平台都接收通知 |
| `/nb notify add <instance_id>` | 添加平台到列表（如 `qq`、`discord`、`telegram`） |
| `/nb notify rm <instance_id>` | 从列表中移除平台 |
| `/nb notify list` | 查看当前通知偏好设置 |

### 三种模式

- **all** — 默认。所有绑定平台都接收 @通知。
- **whitelist** — 仅通过 `notify add` 添加的平台接收通知。
- **blacklist** — 除通过 `notify add` 添加的平台外，其他平台都接收通知。

### 示例

```
/nb notify mode whitelist
/nb notify add discord
/nb notify add qq
/nb notify list
```

设置后，即使绑定了 Telegram，@通知也只会发送到 Discord 和 QQ 绑定的账号。

## `/nb status`

查看 NextBridge 的运行状态与版本信息。

```
/nb status
```

回复内容包含：版本号（稳定版本显示版本号，开发版本显示提交哈希）、运行时长、各平台驱动状态、规则数量等。

## `/nb help`

显示内置命令帮助。

```
/nb help
```

## `/ping`

通过昵称跨平台查找用户并 @ 他们。

```
/ping <昵称>
```

## Discord 原生命令

当 Discord 驱动使用 bot token 运行（且未禁用 `enable_native_commands`）时，NextBridge 会注册原生斜杠命令。它们与上文文本命令等价，但把结构性 token 暴露为子命令与选择菜单，无需手动输入：

```
/nb bind setup
/nb bind confirm code:<验证码>
/nb bind rm [instance_id:<实例 ID>]
/nb bind list
/nb notify mode mode:<all|whitelist|blacklist>
/nb notify add instance_id:<实例 ID>
/nb notify rm instance_id:<实例 ID>
/nb notify list
/nb status
/nb help
/ping
```

- 动作（`setup`、`confirm`、`mode` 等）以子命令形式提供，`mode` 为选择菜单；仅绑定 `<验证码>` 与 `<实例 ID>` 等自由取值需手动输入。
- 根命令名跟随 `command_prefix`。若该前缀不是合法的 Discord 命令名（1–32 个字符，仅小写字母、数字、`-` 或 `_`），驱动会回退为 `nb` 并记录一条警告。
- 修改 `command_prefix` 需重启后才能更新已注册的斜杠命令名。

## 配置

### `mention_notify_control`

```yaml
global:
  mention_notify_control: true   # 默认：启用 /nb notify 命令
  # mention_notify_control: false  # 备选：禁用此功能
```

禁用后，所有绑定平台始终接收 @通知，`/nb notify` 命令返回已禁用提示。
