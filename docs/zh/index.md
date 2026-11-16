---
layout: home

hero:
  name: NextBridge
  text: 连接几乎所有主流聊天平台的聊天桥接工具！
  tagline: 使用一个配置文件连接 QQ、Discord、Telegram、飞书/Lark、钉钉、云湖、KOOK、Matrix、Signal、Slack、Google Chat、Mattermost、VoceChat、Rocket.Chat 等平台。
  image:
    src: https://icons.siiway.org/nextbridge/icon.svg
    alt: NextBridge Logo
  actions:
    - theme: brand
      text: 快速开始
      link: /zh/getting-started
    - theme: alt
      text: 访问 GitHub 仓库
      link: https://github.com/siiway/NextBridge

features:
  - title: 多平台支持
    details: 支持 QQ、Discord、Telegram、飞书/Lark、钉钉、云湖、KOOK、Matrix、Signal、Slack、Google Chat、Mattermost、VoceChat、Rocket.Chat、Webhook 和 WhatsApp。
    link: /zh/platform-support
    linkText: 查看支持状态
  - title: 配置驱动路由
    details: 使用简单的规则文件定义频道之间的消息路由——无需编写代码。
    link: /zh/rules
    linkText: 了解规则详情
  - title: 媒体桥接
    details: 图片、视频、语音消息和文件会自动下载并重新上传到目标平台。支持按实例配置文件大小上限。
  - title: 按频道定制消息格式
    details: 为每个目标平台独立设置消息格式。Discord Webhook 和 Telegram richheader 支持原生用户名和头像显示，QQ 使用简洁的文字前缀。
  - title: 用户指令
    details: 用户可通过 /nb bind 和 /nb bind confirm 跨平台绑定账号，确保完美的跨平台提及和通知。
    link: /zh/user-commands
    linkText: 查看用户指令
  - title: JSON、YAML 和 TOML 配置
    details: 使用你偏好的格式编写配置文件，可随时通过内置 convert 命令互转。
    link: /zh/configuration
    linkText: 配置 NextBridge
  - title: 消息编辑同步
    details: 在 Discord 或 Telegram 编辑消息后，会自动同步更新其他平台上的对应桥接消息。Discord 支持 Webhook 和 Bot 两种编辑方式，Telegram 在编辑时会保留富头部卡片样式。
---
