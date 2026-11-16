import { defineConfig } from 'vitepress'

// This build always represents the current (latest) release line. Historical
// releases are built from their own long-lived `vX.Y-legacy` branches and served
// from the corresponding Pages branch alias, so nothing in this file is
// version-aware beyond the label below.
const VERSION = 'v0.4'

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
        { text: 'Migrating to v0.4', link: `${prefix}/migrate` },
      ],
    },
    {
      text: 'Drivers',
      items: [
        { text: 'Overview', link: `${prefix}/drivers/` },
        { text: 'QQ', link: `${prefix}/drivers/qq` },
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
      ],
    },
    {
      text: 'Extending',
      items: [
        { text: 'Plugin Development', link: `${prefix}/plugins` },
        { text: 'Admin API', link: `${prefix}/admin-api` },
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
        { text: '迁移到 v0.4', link: `${prefix}/migrate` },
      ],
    },
    {
      text: '驱动器',
      items: [
        { text: '概览', link: `${prefix}/drivers/` },
        { text: 'QQ', link: `${prefix}/drivers/qq` },
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
      ],
    },
    {
      text: '扩展',
      items: [
        { text: '插件开发', link: `${prefix}/plugins` },
        { text: '管理 API', link: `${prefix}/admin-api` },
      ],
    },
  ]
}

export default defineConfig({
  title: 'NextBridge',
  description: 'The chat bridge that links up all the major chat platforms!',
  lastUpdated: true,
  cleanUrls: true,
  sitemap: {
    hostname: 'https://nextbridge.siiway.org',
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
          // Version badge only. Historical releases link *here*, so this site
          // never has to enumerate them (which would need editing every release).
          { text: `${VERSION} (latest)`, link: '/en/getting-started' },
        ],
        sidebar: enSidebar(),
        editLink: {
          pattern: 'https://github.com/siiway/NextBridge/edit/main/docs/:path',
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
          // Keep the label parallel to the English one.
          { text: `${VERSION} (latest)`, link: '/zh/getting-started' },
        ],
        sidebar: zhSidebar(),
        editLink: {
          pattern: 'https://github.com/siiway/NextBridge/edit/main/docs/:path',
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
