# KOOK（开黑啦）

KOOK 驱动器使用 [khl-py](https://github.com/TWT233/khl.py) 通过 WebSocket（机器人模式）连接。它从公共文字频道接收 TEXT 和 KMarkdown 消息，并通过 KOOK 机器人 API 发送消息。

## 准备工作

1. 前往 [KOOK 开发者平台](https://developer.kookapp.cn/) 创建一个机器人应用。
2. 在 **机器人** → **机器人连接方式** 中，选择 **WebSocket**。
3. 复制机器人 Token。
4. 将机器人邀请至你的服务器，并赋予其在目标频道读取和发送消息的权限。
5. 获取频道 ID（右键点击频道 → 复制 ID，或从频道 URL 中获取）。

## 配置项

在 `config.json` 的 `kook.<实例ID>` 下添加：

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `token` | 是 | — | 来自 KOOK 开发者平台的机器人 Token |
| `max_file_size` | 否 | `26214400`（25 MB） | 上传附件时单个文件的最大字节数 |

```json
{
  "kook": {
    "kook_main": {
      "token": "your-kook-bot-token",
      "max_file_size": 26214400
    }
  }
}
```

## 规则频道键

在 `rules.json` 的 `channels` 或 `from`/`to` 下使用：

| 键 | 说明 |
|---|---|
| `channel_id` | KOOK 文字频道 ID |

```json
{
  "kook_main": { "channel_id": "1234567890123456" }
}
```

## 接收的消息类型

来自公共文字频道的 TEXT 和 KMarkdown 消息均会被桥接。原始消息内容（包括 KMarkdown 语法）将原样作为消息文本传递。

## 发送

| 附件类型 | 发送方式 |
|---|---|
| `image` | 上传至 KOOK CDN；以 `(img)url(img)` KMarkdown 语法嵌入 |
| `voice` / `video` / `file` | 上传至 KOOK CDN；以 `[文件名](url)` 超链接形式发送 |

当消息包含图片或富头部时，以 `KMarkdown` 类型发送以确保格式正确渲染。无附件的纯文字消息以 `TEXT` 类型发送。

## 注意事项

- 机器人必须在 NextBridge 启动前已加入目标服务器。
- 接收到的 KMarkdown 消息将原样转发，其他平台可能将 KMarkdown 语法（如 `**加粗**`）显示为纯文本。
- KOOK WebSocket 连接由 khl-py 库内部管理自动重连。
