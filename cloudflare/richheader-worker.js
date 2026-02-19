/**
 * Cloudflare Worker — Rich Header OG page
 *
 * Returns a minimal HTML page carrying Open Graph meta tags so that
 * Telegram renders a small link-preview card (avatar + name + secondary
 * text) above the bridged message.
 *
 * Query parameters:
 *   title   – display name / username          (og:title)
 *   content – secondary line, e.g. "id: 123"  (og:description)
 *   avatar  – full avatar URL                  (og:image)
 *
 * Deploy:
 *   1. Create a new Worker in the Cloudflare dashboard and paste this file.
 *   2. Note the worker URL (e.g. https://richheader.yourname.workers.dev).
 *   3. Set "rich_header_host" in your telegram instance config to that URL.
 *
 * Example config.json entry:
 *   "telegram": {
 *     "my_tg": {
 *       "bot_token": "...",
 *       "rich_header_host": "https://richheader.yourname.workers.dev"
 *     }
 *   }
 */

const e = s =>
  String(s)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

export default {
  async fetch(request) {
    const { searchParams } = new URL(request.url);
    const title   = searchParams.get('title')   ?? '';
    const content = searchParams.get('content') ?? '';
    const avatar  = searchParams.get('avatar')  ?? '';

    const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta property="og:type"  content="website">
  <meta property="og:site_name" content="${e(title)}">
  ${content ? `<meta property="og:title" content="${e(content)}">` : ''}
  ${avatar  ? `<meta property="og:image"       content="${e(avatar)}">` : ''}
</head>
<body>There is nothing here.</body>
</html>`;

    return new Response(html, {
      headers: {
        'Content-Type': 'text/html;charset=UTF-8',
        'Cache-Control': 'no-store',
      },
    });
  },
};
