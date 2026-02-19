# 钉钉

钉钉驱动器通过 HTTP Webhook（外发机器人）接收消息，并通过钉钉机器人 v1.0 API 使用 [alibabacloud-dingtalk](https://github.com/aliyun/alibabacloud-dingtalk-sdk) 发送消息。

## 准备工作

1. 在[钉钉开放平台](https://open-dev.dingtalk.com)创建一个企业内部应用。
2. 在**机器人**配置中，将**消息接收模式**设为 **HTTP 模式**。
3. 将消息接收地址设为 `http://your-host:8082/dingtalk/event`。
4. 复制 **App Key**、**App Secret** 和 **机器人 Code**。
5. 如需签名验证，开启签名并复制**签名密钥**。
6. 将机器人添加到目标群组。

::: warning 需要公网可访问的地址
钉钉需要从公网访问你的 HTTP 端点。请使用反向代理、内网穿透工具（如 ngrok）或将服务部署在公网服务器上。
:::

## 配置项

在 `config.json` 的 `dingtalk.<实例ID>` 下添加：

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `app_key` | 是 | — | 钉钉 App Key |
| `app_secret` | 是 | — | 钉钉 App Secret |
| `robot_code` | 是 | — | 机器人 Code，发送消息时必填 |
| `signing_secret` | 否 | — | Webhook 签名密钥；不填则跳过签名验证 |
| `listen_port` | 否 | `8082` | 监听传入事件的 HTTP 端口 |
| `listen_path` | 否 | `"/dingtalk/event"` | 监听传入事件的 HTTP 路径 |

```json
{
  "dingtalk": {
    "dt_main": {
      "app_key": "dingxxxxxxxxxx",
      "app_secret": "your_app_secret",
      "robot_code": "your_robot_code",
      "signing_secret": "your_signing_secret",
      "listen_port": 8082,
      "listen_path": "/dingtalk/event"
    }
  }
}
```

## 规则频道键

在 `rules.json` 的 `channels` 或 `from`/`to` 下使用：

| 键 | 说明 |
|---|---|
| `open_conversation_id` | 目标群组的钉钉开放会话 ID |

```json
{
  "dt_main": { "open_conversation_id": "cidXXXXXXXXXXXXXXX" }
}
```

`open_conversation_id` 包含在群内用户消息的 Webhook 事件 payload 中（`openConversationId` 字段），也可在钉钉开发者后台查看。

## 注意事项

- 目前仅接收**文本消息**，富媒体消息类型在接收端会被忽略。
- 发出的附件以 URL 形式附加到文本消息末尾。
- OAuth 2.0 访问令牌会被缓存，并在过期前 60 秒自动刷新。
- 若未设置 `signing_secret`，则跳过 Webhook 签名验证。生产环境中强烈建议配置签名密钥。
