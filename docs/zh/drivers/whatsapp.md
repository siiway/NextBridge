> 本文档由 AI 编写，已经人工审核。

# WhatsApp

WhatsApp 驱动器使用 [neonize](https://github.com/krypton-byte/neonize)——[go-whatsapp (whatsmeow)](https://github.com/tulir/whatsmeow) 的 Python 绑定——直接连接 WhatsApp Web，**无需 Node.js**。

## 准备工作

1. 在 `config.json` 中添加 WhatsApp 实例配置（见下文）。
2. 启动 NextBridge。首次运行时，终端会打印一个二维码。
3. 打开手机上的 WhatsApp → **已关联设备** → **关联设备**，扫描二维码。
4. 认证状态保存在 `storage_dir` 指定的 SQLite 文件中，重启后无需重新扫码（除非退出登录）。

## 系统要求

neonize 根据不同平台需要安装特定的系统库：

- **Linux (Ubuntu/Debian)**:
  ```bash
  sudo apt install libmagic1
  ```

- **Linux (Fedora/RHEL)**:
  ```bash
  sudo dnf install file-libs
  ```

- **macOS**:
  ```bash
  brew install libmagic
  ```

- **Windows**: `python-magic-bin` 会随 neonize 自动安装。

## 配置项

在 `config.json` 的 `whatsapp.<实例ID>` 下添加：

| 键 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|
| `storage_dir` | 否 | `~/.nextbridge/whatsapp/<实例ID>.db` | 存储认证状态的 SQLite 文件路径 |

```json
{
  "whatsapp": {
    "wa_main": {
      "storage_dir": "/path/to/whatsapp/wa_main.db"
    }
  }
}
```

## 规则频道键

在 `rules.json` 的 `channels` 或 `from`/`to` 下使用：

| 键 | 说明 |
|---|---|
| `chat_id` | WhatsApp JID 字符串。私聊使用 `<手机号>@s.whatsapp.net`，群组使用 `<群组ID>@g.us` |

```json
{
  "wa_main": { "chat_id": "1234567890@s.whatsapp.net" }
}
```

## 接收的消息类型

| WhatsApp 类型 | 附件类型 | 备注 |
|---|---|---|
| 文字消息 | — | 普通对话或扩展文本（回复、链接预览） |
| 图片 | `image` | Caption 作为消息文本 |
| 视频 | `video` | Caption 作为消息文本 |
| 语音 / 音频 | `voice` | 文本设为 `[Voice Message]` |
| 文件 | `file` | Caption 作为消息文本；文件名保留 |

## 发送

发出的消息以纯文本形式发送。若消息包含来自其他平台的附件，则以文本形式回退附加：

```
[Image: photo.jpg]
[File: document.pdf]
```

原生媒体发送（向 WhatsApp 上传图片/文件）尚未实现。

## 注意事项

- **需要 WhatsApp 个人账号**：本驱动器使用 WhatsApp Web 多设备协议（非 Business API），需通过二维码关联一个个人账号。
- **单会话限制**：关联 NextBridge 后，它会占用一个已关联设备名额，但你仍可在手机上正常使用 WhatsApp。
- **获取群组 JID**：收到群消息后，查看日志中打印的 `chat_id` 即为群组 JID。
- **自发消息过滤**：已关联账号自身发送的消息会被自动忽略。
- **状态播报屏蔽**：`status@broadcast` 消息会被自动忽略。
