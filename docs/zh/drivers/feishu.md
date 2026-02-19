# 飞书 / Lark

飞书驱动器通过飞书事件系统推送的 HTTP Webhook 接收消息，并通过飞书 IM v1 API 使用 [lark-oapi](https://github.com/larksuite/oapi-sdk-python) 发送消息。

飞书（中国大陆）和 Lark（国际版）使用相同的 API，共用同一驱动器。

## 准备工作

1. 前往[飞书开放平台](https://open.feishu.cn)（或 [Lark 开发者平台](https://open.larksuite.com)）。
2. 创建一个**自建应用**，并开启 **im:message:receive_v1** 事件订阅。
3. 在**事件订阅**中，将请求 URL 设为 `http://your-host:8080/event`（与 `listen_port` 和 `listen_path` 配置一致）。
4. 复制 **App ID**、**App Secret**、**验证 Token** 和**加密 Key**（不需要加密可留空）。
5. 将应用机器人添加到目标群聊。

::: warning 需要公网可访问的地址
飞书需要从公网访问你的 HTTP 端点。请使用反向代理、内网穿透工具（如 ngrok）或将服务部署在公网服务器上。
:::

## 配置项

在 `config.json` 的 `feishu.<实例ID>` 下添加：

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `app_id` | 是 | — | 飞书/Lark App ID |
| `app_secret` | 是 | — | 飞书/Lark App Secret |
| `verification_token` | 否 | `""` | 开发者后台的事件验证 Token |
| `encrypt_key` | 否 | `""` | 事件加密 Key（留空表示不加密） |
| `listen_port` | 否 | `8080` | 监听传入事件的 HTTP 端口 |
| `listen_path` | 否 | `"/event"` | 监听传入事件的 HTTP 路径 |

```json
{
  "feishu": {
    "fs_main": {
      "app_id": "cli_xxxxxxxxxxxx",
      "app_secret": "your_app_secret",
      "verification_token": "your_verification_token",
      "encrypt_key": "",
      "listen_port": 8080,
      "listen_path": "/event"
    }
  }
}
```

## 规则频道键

在 `rules.json` 的 `channels` 或 `from`/`to` 下使用：

| 键 | 说明 |
|---|---|
| `chat_id` | 飞书开放 Chat ID，如 `"oc_xxxxxxxxxxxxxxxxxx"` |

```json
{
  "fs_main": { "chat_id": "oc_xxxxxxxxxxxxxxxxxx" }
}
```

Chat ID 可在飞书开发者后台查看，也可从机器人在该群收到的事件 payload 中获取。

## 注意事项

- 目前仅接收**文本消息**，其他消息类型（卡片、文件、表情）在接收端会被忽略。
- 发出的附件以 URL 形式附加到文本消息末尾（通过 API 上传文件需要额外权限，暂未实现）。
- 发送者显示名称当前使用其 `open_id`，解析为可读名称需要额外的用户信息 API 调用，暂未实现。
