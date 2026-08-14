# NextBridge

> *The chat bridge that links up all the major chat platforms!*

**Docs (English): <https://nextbridge.siiway.org>**

**文档 (中文): <https://nextbridge.siiway.org/zh>**

## Platform List

 - [x] [Tencent QQ](https://im.qq.com) (with the QQ driver: NapCat, Lagrange, and OneBot 11 protocols)
 - [x] [Discord](https://discord.gg)
 - [x] [Telegram](https://telegram.org)
 - [x] [VoceChat](https://voce.chat)
 - [x] [WhatsApp](https://whatsapp.com) (with [Neonize](https://github.com/krypton-byte/neonize))
 - [x] [DingTalk](https://dingtalk.com) - Not Tested
 - [x] [Feishu](https://feishu.cn) and [Lark](https://larksuite.com)
 - [ ] ~~[WeChat / WeiXin](https://weixin.qq.com)~~ - paused cuz i *(nt)* dont want to get my wechat account banned
 - [x] [Yunhu](https://www.yhchat.com/)
 - [x] [Kook](https://www.kookapp.cn/)
 - [x] [Matrix](https://matrix.org)
 - [x] [Signal](https://signal.org) - Not Tested
 - [x] [Microsoft Teams](https://teams.microsoft.com) - Not Tested
 - [x] [Google Chat](https://chat.google.com) - Not Tested
 - [x] [Mattermost](https://mattermost.com) - Not Tested
 - [x] [Rocket.Chat](https://rocket.chat) - Not Tested
 - [ ] [Tailchat](https://github.com/msgbyte/tailchat)
 - [ ] [Zulip](https://zulip.com)
 - [ ] [LINE](https://line.me)
 - [ ] [Viber](https://viber.com)

## To-Do List

**See <https://glint.siiway.org/shared/58f09c61cf844a2393dcefad1263fe45>**

[![Todo](https://glint.siiway.org/api/shared/58f09c61cf844a2393dcefad1263fe45/todo-list.svg?theme=dark&maxItems=25)](https://glint.siiway.org/shared/58f09c61cf844a2393dcefad1263fe45)

## WebUI Management Plane

NextBridge ships with a built-in WebUI management plane at `http://<host>:<port>/webui`
(default port `9080`), where you can edit the global config, platform instances, and
bridge rules from your browser. Config and rules files are auto-generated with safe
defaults on first startup.

The frontend is built from the separate [webui](https://github.com/LeiSureLyYrsc/webui)
repository — build it and drop the output into this repo's `dist/` directory.

> [!IMPORTANT]
> The default WebUI account is `admin` / `admin`, and the password **must** be
> changed on first login before the panel can be used. If the shared HTTP server
> is exposed to the internet, protect it with HTTPS / a reverse proxy.

Docs: <https://nextbridge.siiway.org>

## Special Thanks

 - NapCat
 - Lagrange.OneBot
 - OneBot v11
 - discord.py
 - python-telegram-bot
 - mautrix-python
 - lark-oapi
 - alibabacloud-dingtalk
 - khl-py
 - yunhu
 - slack-sdk
 - google-auth
 - neonize
 - psycopg2

## License

GNU General Public License v3.0. See [LICENSE](./LICENSE) for details.
