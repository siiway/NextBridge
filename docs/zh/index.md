---
layout: home

hero:
  name: NextBridge
  text: 连接所有主流聊天平台的消息桥接工具！
  tagline: 用一个配置文件将 QQ、Discord、Telegram、飞书、钉钉、云湖、KOOK、Matrix、Signal、Slack 连接在一起。
  actions:
    - theme: brand
      text: 快速开始
      link: /zh/getting-started
    - theme: alt
      text: 在 GitHub 上查看
      link: https://github.com/siiway/NextBridge

features:
  - title: 多平台支持
    details: 开箱即用地支持 QQ（通过 NapCat）、Discord、Telegram、飞书/Lark、钉钉、云湖、KOOK、Matrix、Signal、Slack、Google Chat 和 Mattermost，可通过驱动器扩展更多平台。
  - title: 配置驱动的消息路由
    details: 使用简单的规则文件定义群组之间的消息流向，无需编写代码。使用 connect 规则一键互联，或使用 forward 规则精细控制消息方向。
  - title: 媒体文件桥接
    details: 图片、视频、语音消息和文件会自动从源平台下载并重新上传到目标平台，支持按实例配置文件大小上限。
  - title: 按平台定制消息格式
    details: 为每个目标平台独立设置消息格式。Discord Webhook 支持原生用户名和头像显示，QQ 和 Telegram 使用简洁的文字前缀。
  - title: 支持 JSON、YAML 和 TOML 配置
    details: 使用你喜欢的格式编写配置文件，并可随时通过内置 convert 命令在各格式之间互转。
---
