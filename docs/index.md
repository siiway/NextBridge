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
      link: /getting-started
    - theme: alt
      text: Visit GitHub Repo
      link: https://github.com/siiway/NextBridge

features:
  - title: Multi-platform
    details: Supports QQ (via NapCat), Discord, Telegram, Feishu/Lark, DingTalk, Yunhu, KOOK, Matrix, Signal, Slack, Google Chat, Mattermost, VoceChat, Rocket.Chat, Webhook and WhatsApp.
    link: /platform-support
    linkText: View support status
  - title: Config-driven routing
    details: Define which channels talk to each other using a simple rules file — no code needed. Use connect rules to link groups, or forward rules for fine-grained control. Configure custom proxy settings for each driver individually.
    link: /rules
    linkText: Learn more about rules
  - title: Media bridging
    details: Images, videos, voice messages, and files are automatically downloaded and re-uploaded to the target platform. Configurable per-instance size limits.
  - title: Per-channel message formatting
    details: Customize the message format for each target platform independently. Discord webhooks and Telegram richheader get native username and avatar; QQ gets clean text prefixes.
  - title: User Commands
    details: Users can bind their accounts across platforms with /bind and /confirm to ensure perfect cross-platform mentions and notifications. Link multiple identities into a single global ID.
    link: /user-commands
    linkText: View user commands
  - title: JSON, YAML, and TOML config
    details: Write your config in whichever format you prefer. Convert between formats at any time with the built-in convert command.
    link: /configuration
    linkText: Configure NextBridge
---
