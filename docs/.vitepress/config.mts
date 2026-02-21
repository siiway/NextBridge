import { defineConfig } from 'vitepress'

const enSidebar = [
  {
    text: 'Guide',
    items: [
      { text: 'Getting Started', link: '/getting-started' },
      { text: 'Configuration', link: '/configuration' },
      { text: 'Rules', link: '/rules' },
    ],
  },
  {
    text: 'Drivers',
    items: [
      { text: 'Overview', link: '/drivers/' },
      { text: 'NapCat (QQ)', link: '/drivers/napcat' },
      { text: 'Discord', link: '/drivers/discord' },
      { text: 'Telegram', link: '/drivers/telegram' },
      { text: 'Feishu / Lark', link: '/drivers/feishu' },
      { text: 'DingTalk', link: '/drivers/dingtalk' },
      { text: 'Yunhu', link: '/drivers/yunhu' },
      { text: 'KOOK', link: '/drivers/kook' },
      { text: 'Matrix', link: '/drivers/matrix' },
      { text: 'Signal', link: '/drivers/signal' },
      { text: 'Slack', link: '/drivers/slack' },
      { text: 'Microsoft Teams', link: '/drivers/teams' },
      { text: 'Google Chat', link: '/drivers/googlechat' },
      { text: 'Mattermost', link: '/drivers/mattermost' },
      { text: 'Webhook', link: '/drivers/webhook' },
    ],
  },
]

const zhSidebar = [
  {
    text: '指南',
    items: [
      { text: '快速开始', link: '/zh/getting-started' },
      { text: '配置文件', link: '/zh/configuration' },
      { text: '规则配置', link: '/zh/rules' },
    ],
  },
  {
    text: '驱动器',
    items: [
      { text: '概览', link: '/zh/drivers/' },
      { text: 'NapCat (QQ)', link: '/zh/drivers/napcat' },
      { text: 'Discord', link: '/zh/drivers/discord' },
      { text: 'Telegram', link: '/zh/drivers/telegram' },
      { text: '飞书 / Lark', link: '/zh/drivers/feishu' },
      { text: '钉钉', link: '/zh/drivers/dingtalk' },
      { text: '云湖', link: '/zh/drivers/yunhu' },
      { text: 'KOOK', link: '/zh/drivers/kook' },
      { text: 'Matrix', link: '/zh/drivers/matrix' },
      { text: 'Signal', link: '/zh/drivers/signal' },
      { text: 'Slack', link: '/zh/drivers/slack' },
      { text: 'Microsoft Teams', link: '/zh/drivers/teams' },
      { text: 'Google Chat', link: '/zh/drivers/googlechat' },
      { text: 'Mattermost', link: '/zh/drivers/mattermost' },
      { text: 'Webhook', link: '/zh/drivers/webhook' },
    ],
  },
]

export default defineConfig({
  title: 'NextBridge',
  description: 'The chat bridge that links up all the major chat platforms!',

  locales: {
    root: {
      label: 'English',
      lang: 'en-US',
      themeConfig: {
        nav: [
          { text: 'Guide', link: '/getting-started' },
          { text: 'Drivers', link: '/drivers/' },
        ],
        sidebar: enSidebar,
      },
    },
    zh: {
      label: '简体中文',
      lang: 'zh-CN',
      themeConfig: {
        nav: [
          { text: '指南', link: '/zh/getting-started' },
          { text: '驱动器', link: '/zh/drivers/' },
        ],
        sidebar: zhSidebar,
      },
    },
  },

  themeConfig: {
    socialLinks: [
      { icon: 'github', link: 'https://github.com/siiway/NextBridge' },
    ],
  },
})
