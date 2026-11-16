---
title: 迁移到 v0.4
---

# 迁移到 v0.4

::: tip 从更老的版本升级？
本页只覆盖 **v0.3 → v0.4**。如果你还在 v0.3 或更早，请先完成 [v0.3 迁移页](https://v0-3-legacy.nextbridge.pages.dev/zh/migrate) —— 迁移步骤需要逐级应用。

English version: [Migrating to v0.4](/en/migrate)。
:::

NextBridge 在 1.0 之前不保证向后兼容，因此小版本升级也可能改动配置键和行为。本页列出从 v0.3 升级到 v0.4 时需要注意的全部内容。

## 升级前

1. **备份 `data/`**。里面有 `config.*`、`rules.*`、`data.db` 以及可选的 `cqface-map.yaml`。
2. **检查配置键**。v0.4 会严格校验配置文件，旧版本遗留的键会在启动时直接报错，而不再被静默忽略。[配置文件参考](/zh/configuration)是最权威的依据。

## 配置变更

### 驱动器键名

v0.3 → v0.4 之间没有任何驱动器改名，v0.3 的配置键名可以直接沿用。

作为参考：QQ 驱动在 **v0.3** 改名为 `qq`（v0.2 及更早是 `napcat`）。如果你升级的是 v0.3 之前的配置，需要先把这个键改掉 —— NextBridge 按配置键去找驱动器模块，找不到会跳过该实例并打印警告。

### 新增全局配置段

v0.4 新增了若干 `global.*` 配置段。全部可选且有合理默认值，以下建议过一遍：

| 键 | 你可能需要它的原因 |
| --- | --- |
| `global.http` | Webhook 驱动器共用的 HTTP 服务器。云湖不再自己占用端口（见下）。 |
| `global.plugins` | 驱动/插件选择、管理 API 凭据、重启策略。 |
| `global.metrics` | `/_nextbridge/metrics` 的 Prometheus 计数器。 |
| `global.middleware` | 收发中间件管线。 |
| `global.send_timeout` | 慢速发送转入后台队列。 |
| `global.sanitize_nickname` | 清除发送者昵称里的零宽字符与双向控制符。 |

### 各驱动器键变更

**移除 / 改名：**

| 驱动器 | v0.3 | v0.4 |
| --- | --- | --- |
| `discord` | `send_as_bot_when_using_cqface_emoji` | `cqface_webhook_fallback`（`"bot"` / `"unicode"`） |
| `yunhu` | `webhook_port` | 已移除 —— webhook 由共用的 `global.http` 服务器提供，见 `webhook_path` |
| `qq` | `forward_render_cqface_gif` | `cqface_gif_host`（旧键仍作为废弃别名可用） |

**新增：**

- `discord`：`enable_recall`、`enable_native_commands`、提及控制（`allow_mentions_everyone` / `allow_mentions_users` / `allow_mentions_roles`、 `sanitize_mass_mentions`）、`auto_link_image_hosts`、 `auto_link_image_show_original_url`
- `telegram`：`enable_recall`、`sanitize_accidental_mentions`、`photo_padding_color`
- `qq`：`connection_mode`、`reverse_ws_path`、`edit_via_reply`、`edit_prefix`、 `enable_recall`、`cqface_gif_host`
- `dingtalk` / `feishu` / `googlechat` / `rocketchat` / `slack` / `teams` / `vocechat` / `yunhu`：`webhook_secret`

## 行为变更

- **规则文件在启动时校验。** 格式错误的 `rules.*` 会拒绝启动，而不是在运行时静默忽略规则。
- **`cqface_mode: "gif"` 支持远程拉取。** 本地 `db/cqface-gif/` 缺失的表情会从 `cqface_gif_host` 下载，而不是直接丢弃。GIF 现在位于
  <https://cqface.p.wyf9.top/dist/>；旧的 `nextbridge.siiway.org/db/cqface-gif/` 会 301 到新地址。
- **管理 API 默认拒绝访问（fail-closed）。** 禁用管理 API 时，只有 `/_nextbridge/health` 公开。
- **慢速发送不再阻塞队列。** 超过 `send_timeout` 的消息会转后台继续发送。

## 升级后

1. 启动 NextBridge，留意启动日志中的配置校验错误。
2. 数据库会自动迁移（`5 -> 6` 新增 `metrics_counters` 表）。
3. 若使用管理 API，请设置 `global.plugins.admin.user` / `password`。
4. 可用 `SIGHUP` 或管理 API 热重载配置，无需重启。
