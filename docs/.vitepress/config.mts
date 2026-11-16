import { defineConfig } from 'vitepress'

// Frozen documentation for the v0.3 release line. This branch (`v0.3-legacy`)
// is deployed to its Pages branch alias; the current release lives at
// https://nextbridge.siiway.org and is built from `main`.
const VERSION = 'v0.3'

// Production docs. Referenced by origin only, with no version number, so this
// frozen branch never needs editing when a new release ships.
const CURRENT_ORIGIN = 'https://nextbridge.siiway.org'

function enSidebar() {
  const prefix = '/en'
  return [
    {
      text: 'Guide',
      items: [
        { text: 'Getting Started', link: `${prefix}/getting-started` },
        { text: 'Configuration', link: `${prefix}/configuration` },
        { text: 'Rules', link: `${prefix}/rules` },
        { text: 'User Commands', link: `${prefix}/user-commands` },
        { text: 'Platform Support', link: `${prefix}/platform-support` },
        { text: 'Migrating to v0.3', link: `${prefix}/migrate` },
      ],
    },
    {
      text: 'Drivers',
      items: [
        { text: 'Overview', link: `${prefix}/drivers/` },
        { text: 'NapCat (QQ)', link: `${prefix}/drivers/napcat` },
        { text: 'Discord', link: `${prefix}/drivers/discord` },
        { text: 'Telegram', link: `${prefix}/drivers/telegram` },
        { text: 'Feishu / Lark', link: `${prefix}/drivers/feishu` },
        { text: 'DingTalk', link: `${prefix}/drivers/dingtalk` },
        { text: 'Yunhu', link: `${prefix}/drivers/yunhu` },
        { text: 'KOOK', link: `${prefix}/drivers/kook` },
        { text: 'Matrix', link: `${prefix}/drivers/matrix` },
        { text: 'Signal', link: `${prefix}/drivers/signal` },
        { text: 'Slack', link: `${prefix}/drivers/slack` },
        { text: 'Microsoft Teams', link: `${prefix}/drivers/teams` },
        { text: 'Google Chat', link: `${prefix}/drivers/googlechat` },
        { text: 'Mattermost', link: `${prefix}/drivers/mattermost` },
        { text: 'VoceChat', link: `${prefix}/drivers/vocechat` },
        { text: 'Rocket.Chat', link: `${prefix}/drivers/rocketchat` },
        { text: 'Webhook', link: `${prefix}/drivers/webhook` },
        { text: 'WhatsApp', link: `${prefix}/drivers/whatsapp` },
      ],
    },
  ]
}

function zhSidebar() {
  const prefix = '/zh'
  return [
    {
      text: '指南',
      items: [
        { text: '快速开始', link: `${prefix}/getting-started` },
        { text: '配置文件', link: `${prefix}/configuration` },
        { text: '规则配置', link: `${prefix}/rules` },
        { text: '用户指令', link: `${prefix}/user-commands` },
        { text: '平台支持状态', link: `${prefix}/platform-support` },
        { text: '迁移到 v0.3', link: `${prefix}/migrate` },
      ],
    },
    {
      text: '驱动器',
      items: [
        { text: '概览', link: `${prefix}/drivers/` },
        { text: 'NapCat (QQ)', link: `${prefix}/drivers/napcat` },
        { text: 'Discord', link: `${prefix}/drivers/discord` },
        { text: 'Telegram', link: `${prefix}/drivers/telegram` },
        { text: '飞书 / Lark', link: `${prefix}/drivers/feishu` },
        { text: '钉钉', link: `${prefix}/drivers/dingtalk` },
        { text: '云湖', link: `${prefix}/drivers/yunhu` },
        { text: 'KOOK', link: `${prefix}/drivers/kook` },
        { text: 'Matrix', link: `${prefix}/drivers/matrix` },
        { text: 'Signal', link: `${prefix}/drivers/signal` },
        { text: 'Slack', link: `${prefix}/drivers/slack` },
        { text: 'Microsoft Teams', link: `${prefix}/drivers/teams` },
        { text: 'Google Chat', link: `${prefix}/drivers/googlechat` },
        { text: 'Mattermost', link: `${prefix}/drivers/mattermost` },
        { text: 'VoceChat', link: `${prefix}/drivers/vocechat` },
        { text: 'Rocket.Chat', link: `${prefix}/drivers/rocketchat` },
        { text: 'Webhook', link: `${prefix}/drivers/webhook` },
        { text: 'WhatsApp', link: `${prefix}/drivers/whatsapp` },
      ],
    },
  ]
}

export default defineConfig({
  // Historical deployment: the title must make clear which release this is.
  // Renders as "<page> | NextBridge Legacy v0.3".
  title: `NextBridge Legacy ${VERSION}`,
  description: `Frozen NextBridge ${VERSION} documentation. The latest release is at ${CURRENT_ORIGIN}.`,
  lastUpdated: true,
  cleanUrls: true,
  sitemap: {
    hostname: 'https://v0-3-legacy.nextbridge.pages.dev',
  },

  head: [
    ['meta', { name: 'theme-color', content: '#0078d4' }],
    [
      'link',
      {
        rel: 'icon',
        type: 'image/svg+xml',
        href: 'https://icons.siiway.org/nextbridge/icon.svg',
      },
    ],
  ],

  locales: {
    en: {
      label: 'English',
      lang: 'en-US',
      description: 'The chat bridge that links up all the major chat platforms!',
      themeConfig: {
        nav: [
          { text: 'Guide', link: '/en/getting-started' },
          { text: 'Drivers', link: '/en/drivers/' },
          // Only link to the current docs, by origin — never enumerate
          // versions, otherwise every legacy branch needs a commit per release.
          { text: `Legacy ${VERSION}`, items: [
            {
              text: 'Latest release docs',
              link: `${CURRENT_ORIGIN}/en/getting-started`,
            },
          ] },
        ],
        sidebar: enSidebar(),
        editLink: {
          pattern: 'https://github.com/siiway/NextBridge/edit/v0.3-legacy/docs/:path',
          text: 'Edit this page on GitHub',
        },
        lastUpdated: {
          text: 'Updated at',
        },
      },
    },
    zh: {
      label: '简体中文',
      lang: 'zh-CN',
      description: '连接几乎所有主流聊天平台的聊天桥接工具！',
      themeConfig: {
        nav: [
          { text: '指南', link: '/zh/getting-started' },
          { text: '驱动器', link: '/zh/drivers/' },
          { text: `Legacy ${VERSION}`, items: [
            {
              text: '最新版本文档',
              link: `${CURRENT_ORIGIN}/zh/getting-started`,
            },
          ] },
        ],
        sidebar: zhSidebar(),
        editLink: {
          pattern: 'https://github.com/siiway/NextBridge/edit/v0.3-legacy/docs/:path',
          text: '在 GitHub 上编辑本页',
        },
        lastUpdated: {
          text: '本页最后更新于',
        },
        outline: {
          label: '本页目录',
        },
        docFooter: {
          prev: '上一篇',
          next: '下一篇',
        },
      },
    },
  },

  themeConfig: {
    socialLinks: [
      { icon: 'github', link: 'https://github.com/siiway/NextBridge' },
    ],
    logo: {
      light: 'https://icons.siiway.org/nextbridge/icon.svg',
      dark: 'https://icons.siiway.org/nextbridge/icon.svg',
      alt: 'NextBridge',
    },

    search: {
      provider: 'local',
      options: {
        locales: {
          '/en/': {},
          '/zh/': {
            translations: {
              button: {
                buttonText: '搜索',
                buttonAriaLabel: '搜索',
              },
              modal: {
                displayDetails: '显示详细列表',
                resetButtonTitle: '重置搜索',
                backButtonTitle: '关闭搜索',
                noResultsText: '没有结果',
                footer: {
                  selectText: '选择',
                  selectKeyAriaLabel: '输入',
                  navigateText: '导航',
                  navigateUpKeyAriaLabel: '上箭头',
                  navigateDownKeyAriaLabel: '下箭头',
                  closeText: '关闭',
                  closeKeyAriaLabel: 'Esc',
                },
              },
            },
          },
        },
      },
    },
  },
})
