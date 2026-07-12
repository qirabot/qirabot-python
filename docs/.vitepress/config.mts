import { defineConfig } from 'vitepress'

// Docs site for qirabot.com/docs. Deployed by .github/workflows/docs-deploy.yml
// to the website S3 bucket under the docs/ prefix; the marketing site's
// deploy-s3.sh excludes docs/* so the two deploys never touch each other.
// URLs keep the .html suffix (cleanUrls: false, the default) because the S3
// REST origin serves exact keys; directory URLs (/docs/, /docs/guide/) are
// rewritten to index.html by the qirabot-website-dir-index CloudFront function.
export default defineConfig({
  base: '/docs/',
  title: 'Qirabot Docs',
  description:
    'AI vision-driven GUI automation for browsers, Android, iOS, desktops, and games — no DOM, no selectors. Python SDK and CLI.',
  head: [
    [
      'link',
      {
        rel: 'icon',
        type: 'image/svg+xml',
        // Same geometric "Q" favicon as the marketing site (see website/index.html).
        href: 'data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><defs><linearGradient id=%22g%22 x1=%220%22 y1=%220%22 x2=%221%22 y2=%221%22><stop offset=%220%22 stop-color=%22%238b5cf6%22/><stop offset=%221%22 stop-color=%22%236366f1%22/></linearGradient></defs><rect width=%22100%22 height=%22100%22 rx=%2222%22 fill=%22url(%23g)%22/><circle cx=%2250%22 cy=%2246%22 r=%2221%22 fill=%22none%22 stroke=%22white%22 stroke-width=%2211%22/><line x1=%2257%22 y1=%2253%22 x2=%2274%22 y2=%2271%22 stroke=%22white%22 stroke-width=%2211%22 stroke-linecap=%22round%22/></svg>',
      },
    ],
  ],
  sitemap: {
    hostname: 'https://qirabot.com/docs/',
  },
  themeConfig: {
    nav: [
      { text: 'Guide', link: '/guide/quickstart' },
      { text: 'Backends', link: '/backends/browser' },
      { text: 'Dashboard', link: 'https://app.qirabot.com' },
      { text: 'qirabot.com', link: 'https://qirabot.com' },
    ],
    sidebar: [
      {
        text: 'Getting Started',
        items: [
          { text: 'Installation', link: '/guide/installation' },
          { text: 'Quick Start', link: '/guide/quickstart' },
          { text: 'CLI Reference', link: '/guide/cli' },
        ],
      },
      {
        text: 'Platform Backends',
        items: [
          { text: 'Browser (Playwright)', link: '/backends/browser' },
          { text: 'Android — direct over adb', link: '/backends/android' },
          { text: 'iOS — WDA, no Appium', link: '/backends/ios' },
          { text: 'Windows & Games', link: '/backends/windows-games' },
          { text: 'Desktop (pyautogui)', link: '/backends/desktop' },
          { text: 'Custom Adapters', link: '/backends/custom-adapters' },
        ],
      },
    ],
    socialLinks: [{ icon: 'github', link: 'https://github.com/qirabot/qirabot-python' }],
    editLink: {
      pattern: 'https://github.com/qirabot/qirabot-python/edit/main/docs/:path',
      text: 'Edit this page on GitHub',
    },
    search: { provider: 'local' },
    footer: {
      message: 'Released under the MIT License.',
      copyright: '© Qirabot Platform',
    },
  },
})
