> 本文档由 AI 编写，已经人工审核。

# 管理 API

NextBridge 提供一组用于运行时查看与管理的 HTTP API，由共享 HTTP 服务器在 `/_nextbridge` 前缀下提供。

::: warning 默认关闭
仅当 `global.plugins.admin.enable` 为 `true` 且设置了密码时，该 API 才可访问。否则除 `GET /_nextbridge/health` 外的所有路由都返回 `404`。
:::

## 鉴权

除 `GET /_nextbridge/health` 外，所有路由都需要 HTTP Basic Auth，凭据来自：

```yaml
global:
  plugins:
    admin:
      enable: true
      user: admin
      password: change-me
```

鉴权为 fail-closed：管理 API 未启用时，受保护的路由根本不存在。鉴权失败会记入审计日志。

## 响应格式

除 `GET /_nextbridge/metrics` 外，所有响应都使用统一的信封结构；metrics 端点返回 Prometheus 文本格式。

成功：

```json
{ "ok": true, "data": { } }
```

错误：

```json
{
  "ok": false,
  "error": {
    "code": "invalid_rules",
    "message": "人类可读的信息",
    "details": null
  }
}
```

常见状态码：`400` 校验错误、`401` 鉴权失败、`404` 目标不存在、`409` 乐观锁冲突、`503` 重载引擎不可用。

## 读端点

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/_nextbridge/health` | 存活探针。公开，无需鉴权。 |
| `GET` | `/_nextbridge/drivers` | 驱动器实例状态 |
| `GET` | `/_nextbridge/plugins` | 插件状态 |
| `GET` | `/_nextbridge/metrics` | Prometheus 文本格式指标 |
| `GET` | `/_nextbridge/rules` | 当前规则及文件路径、内容哈希 |
| `GET` | `/_nextbridge/config` | 当前配置，敏感值已脱敏 |

## 规则

规则存储在规则文件（`rules.yaml` / `rules.json` / `rules.toml`）中，文件始终是真源。每次写入都会经过校验、备份（`.bak`）、原子写入，然后热重载。

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/_nextbridge/admin/rules` | 追加单条规则（请求体为一个规则对象） |
| `PUT` | `/_nextbridge/admin/rules` | 替换整个规则列表（请求体 `{"rules": [...]}`） |
| `PATCH` | `/_nextbridge/admin/rules/{id}` | 将请求体合并进指定 id 的规则 |
| `DELETE` | `/_nextbridge/admin/rules/{id}` | 删除指定 id 的规则 |

### 乐观并发

为避免覆盖 API 之外做出的编辑，请将最近一次读取得到的 `sha256`（来自 `GET /_nextbridge/rules`）作为 `If-Match` 头发送。若文件已变化，请求会以 `409 conflict` 失败。加 `?force=true` 可强制覆盖。

## 配置

| 方法 | 路径 | 说明 |
|---|---|---|
| `PATCH` | `/_nextbridge/admin/config` | 更新可热重载的全局键 |

仅允许在运行时修改以下键（请求体 `{"keys": {"command_prefix": "nb"}}`）；其它键返回 `400 not_hot_reloadable`，`details` 中给出允许的键集合：

`command_prefix`、`strict_echo_match`、`fuzzy_mention_match`、`mention_notify_control`、`send_timeout`、`sanitize_nickname`。

## 插件

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/_nextbridge/admin/plugins/{name}/enable` | 启用插件 |
| `POST` | `/_nextbridge/admin/plugins/{name}/disable` | 禁用插件 |
| `POST` | `/_nextbridge/admin/plugins/{name}/restart` | `disable → unload → load → enable` |

当仍有插件依赖目标插件时，禁用会以 `409` 失败。

## 驱动器

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/_nextbridge/admin/drivers/{instance_id}/restart` | 以当前配置重启驱动器 |
| `POST` | `/_nextbridge/admin/drivers/{instance_id}/reload` | 重读配置并重建驱动器实例 |
| `POST` | `/_nextbridge/admin/reload/{instance_id}` | **已废弃**，`restart` 的别名 |

重载会依据磁盘上的配置重建实例。驱动器 webhook 的 HTTP 挂载路径无法在运行时更改。

## 全量重载

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/_nextbridge/admin/reload` | 重载配置、规则以及所有有改动的驱动器 |

## SIGHUP

向进程发送 `SIGHUP` 会执行与 `POST /_nextbridge/admin/reload` 相同的全量重载。

## 审计日志

每次写操作与鉴权失败都会以每行一个 JSON 对象的形式追加到 `logs/audit.log`（按 `global.log.*` 的轮换设置轮换），并作为 `audit.<event>` 事件发布到事件总线。字段：

`ts`、`event`、`actor`、`source_ip`、`target`、`before`、`after`、`result`、`error`。

`before` / `after` 仅保留最后 500 个字符。
