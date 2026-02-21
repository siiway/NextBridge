# Webhook

Webhook 驱动器是一个**仅发送**的通用驱动器。当消息被路由到 webhook 实例时，NextBridge 会将 JSON 数据包 POST 到配置的 URL。该驱动器没有接收端——不消费任何传入事件。

可用于将桥接流量推送到任意 HTTP 端点：自定义机器人、n8n/Make/Zapier 工作流、日志服务等。

## 配置项

在 `config.json` 的 `webhook.<实例ID>` 下添加：

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `url` | 是 | — | 目标 HTTP 端点 |
| `method` | 否 | `"POST"` | HTTP 方法：`"POST"`、`"PUT"` 或 `"PATCH"` |
| `headers` | 否 | `{}` | 额外的请求头（如用于鉴权） |

```json
{
  "webhook": {
    "my_hook": {
      "url": "https://example.com/bridge-events",
      "headers": {
        "Authorization": "Bearer my-secret-token"
      }
    }
  }
}
```

## 规则频道键

无。URL 由实例配置固定，不需要频道键。规则中的频道字典会被透传到 payload，但不参与路由。

```json
{
  "my_hook": {}
}
```

## Payload 格式

每条消息会以如下 JSON 格式 POST：

```json
{
  "text": "格式化后的消息文本",
  "channel": { "...": "规则频道字典" },
  "attachments": [
    { "type": "image", "url": "https://...", "name": "photo.jpg", "size": 12345 }
  ]
}
```

规则 `msg` 配置块中的额外字段会合并到顶层。例如，若规则中包含 `"webhook_title": "{username}"`，payload 中也会出现 `"webhook_title": "Alice"`。

如需在 payload 中携带发送者信息，可在规则的 `msg` 块中使用格式变量：

```json
{
  "msg": {
    "user":       "{username}",
    "user_id":    "{user_id}",
    "platform":   "{platform}",
    "avatar":     "{user_avatar}"
  }
}
```

## 注意事项

- 若格式化文本中存在 `rich_header` 标签，会将其作为 `[标题 · 内容]` 前缀拼入 `text`，**不会**作为独立字段出现在 payload 中。
- 附件仅携带元数据（`type`、`url`、`name`、`size`），不发送原始字节——接收端若需文件内容，请自行从 `url` 下载。
- HTTP 200、201、202、204 均视为发送成功。
