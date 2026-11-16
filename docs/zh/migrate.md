---
title: 迁移到 v0.3
---

# 迁移到 v0.3

::: tip 这是一个冻结页面
你正在阅读 **v0.3** 的文档。最新版本见
[v0.4](https://nextbridge.siiway.org/zh/migrate)。
:::

本页覆盖 **v0.2.1 → v0.3**。如果你用的版本更早，请先升级到 v0.2.1。

## 升级前

1. **备份 `data/`**（`config.*`、`rules.*`、`data.db`）。
2. **通读一遍配置**。v0.3 会严格校验驱动器配置，以前被静默忽略的键现在会在启动时
   直接报错。

## 配置变更

### QQ 配置键改名

QQ 驱动从 `napcat` 改成了 `qq`，因为它现在支持三种后端而不只是 NapCat：

```diff
-  "napcat": {
+  "qq": {
     "qq_main": {
+      "protocol": "napcat",
       "ws_url": "ws://127.0.0.1:3001"
     }
   }
```

`protocol` 可选 `"napcat"`（默认）、`"lagrange"`、`"onebot_v11"`。

### 新增 `global` 键

| 键 | 说明 |
| --- | --- |
| `global.command_prefix` | 内置指令前缀，默认 `nb`（不带斜杠）。 |
| `global.base_url` | 生成对外链接时使用的公开 URL。 |
| `global.http` | Webhook 驱动器共用的 HTTP 服务器（`host` / `port` / `root_path` / `log_level` / `enable`）。 |

### 各驱动器键变更

**移除 / 改名：**

| 驱动器 | v0.2.1 | v0.3 |
| --- | --- | --- |
| `discord` | `send_as_bot_when_using_cqface_emoji` | `cqface_webhook_fallback`（`"bot"` / `"unicode"`） |
| `yunhu` | `webhook_port` | 已移除 —— webhook 由共用的 `global.http` 服务器提供 |
| `feishu` | `listen_port` | 已移除 —— 同上，由 `global.http` 提供 |

**新增：**

- `qq`：`protocol`、`ws_ssl_verify`，以及整套 `forward_render_*`
  （`forward_render_enabled`、`_ttl_seconds`、`_mount_path`、`_persist_enabled`、
  `_image_method`、`_asset_ttl_seconds`、`_base_url`、`_cqface_gif`）
- `discord`：`allow_mentions_everyone`、`allow_mentions_users`、
  `allow_mentions_roles`、`sanitize_mass_mentions`
- `telegram`：`photo_padding_color`

## 行为变更

- **合并转发渲染**现在可以输出为 HTML 页面，而不再是纯文本摘要。用
  `forward_render_enabled` 开启，并把 `forward_render_base_url` 指向你的公网地址。
- **QQ 表情**可以作为 GIF 附件桥接（`cqface_mode: "gif"`），也可以作为
  `:cqfaceNNN:` 内联标记由各平台自行展开（`"emoji"`）。
- **Webhook 驱动器共用一个 HTTP 服务器**，云湖和飞书不再各自需要 `*_port` 配置。

## 升级后

1. 启动 NextBridge，检查启动日志中的配置校验错误。
2. 若使用 webhook 驱动器，确认 `global.http.enable` 为 `"true"`（或至少有一个
   webhook 驱动器实例挂载了路由）。
