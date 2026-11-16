---
layout: home

hero:
  name: NextBridge
  text: The chat bridge that links up all the major chat platforms!
  tagline: Connect QQ, Discord, Telegram, Feishu/Lark, DingTalk, Yunhu, KOOK, Matrix, Signal, Slack, Google Chat, Mattermost, VoceChat, Rocket.Chat — and more — with a single config file.
  image:
    src: https://icons.siiway.org/nextbridge/icon.svg
    alt: NextBridge Logo
  actions:
    - theme: brand
      text: Get Started
      link: /en/getting-started
    - theme: alt
      text: Visit GitHub Repo
      link: https://github.com/siiway/NextBridge

features:
  - title: Multi-platform
    details: Supports QQ, Discord, Telegram, Feishu/Lark, DingTalk, Yunhu, KOOK, Matrix, Signal, Slack, Google Chat, Mattermost, VoceChat, Rocket.Chat, Webhook and WhatsApp.
    link: /en/platform-support
    linkText: View support status
  - title: Config-driven routing
    details: Define which channels talk to each other using a simple rules file — no code needed.
    link: /en/rules
    linkText: Learn more about rules
  - title: Media bridging
    details: Images, videos, voice messages, and files are automatically downloaded and re-uploaded to the target platform. Configurable per-instance size limits.
  - title: Per-channel message formatting
    details: Customize the message format for each target platform independently. Discord webhooks and Telegram richheader get native username and avatar; QQ gets clean text prefixes.
  - title: User Commands
    details: Users can bind their accounts across platforms with /nb bind and /nb bind confirm to ensure perfect cross-platform mentions and notifications.
    link: /en/user-commands
    linkText: View user commands
  - title: JSON, YAML, and TOML config
    details: Write your config in whichever format you prefer. Convert between formats at any time with the built-in convert command.
    link: /en/configuration
    linkText: Configure NextBridge
  - title: Message Edit Sync
    details: Edits made on Discord or Telegram are automatically synced to bridged messages on the other platform. Discord supports both webhook and bot edit modes; Telegram preserves the rich-header card on edit.
---
