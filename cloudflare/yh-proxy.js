/**
 * Cloudflare Worker — NextBridge media proxy
 *
 * Two endpoints:
 *
 *   GET /pfp?url=<encoded>
 *     Proxies Yunhu CDN avatar URLs, injecting the Referer header that
 *     Yunhu's image CDN requires.
 *     Allowed origins: *.jwznb.com, *.jwzhd.com
 *
 *   GET /media?url=<encoded>
 *     Proxies external media (e.g. Discord CDN) that is blocked in China,
 *     so Yunhu's servers can fetch attachments forwarded from other platforms.
 *     Allowed origins: *.discordapp.com, *.discordapp.net, *.discord.com
 *
 * Deploy:
 *   1. Create a new Worker in the Cloudflare dashboard and paste this file.
 *   2. Note the worker URL (e.g. https://proxy.yourname.workers.dev).
 *   3. Set "proxy_host" in your yunhu instance config to that URL.
 *
 * Example config.json entry:
 *   "yunhu": {
 *     "yh_main": {
 *       "token": "...",
 *       "proxy_host": "https://yh-proxy.yourname.workers.dev"
 *     }
 *   }
 */

const YUNHU_REFERER = 'https://myapp.jwznb.com';

const YUNHU_HOSTS   = ['.jwznb.com', '.jwzhd.com'];
const DISCORD_HOSTS = ['.discordapp.com', '.discordapp.net', '.discord.com'];

const MIME_EXT = {
  'image/jpeg': 'jpg',
  'image/png':  'png',
  'image/gif':  'gif',
  'image/webp': 'webp',
  'video/mp4':  'mp4',
  'video/webm': 'webm',
  'audio/ogg':  'ogg',
  'audio/mpeg': 'mp3',
  'audio/aac':  'aac',
  'audio/amr':  'amr',
};

function hostAllowed(hostname, allowlist) {
  return allowlist.some(suffix => hostname === suffix.slice(1) || hostname.endsWith(suffix));
}

async function proxyUrl(url, extraHeaders = {}) {
  const upstream = await fetch(url, {
    headers: { 'User-Agent': 'Mozilla/5.0', ...extraHeaders },
  });

  const contentType = upstream.headers.get('Content-Type') ?? 'application/octet-stream';
  const mime = contentType.split(';')[0].trim();
  const ext = MIME_EXT[mime];

  // Build a sane filename: take the stem from the upstream URL and replace
  // whatever extension (e.g. .tmp) with one derived from the actual MIME type.
  const stem = new URL(url).pathname.split('/').pop().replace(/\.[^.]+$/, '') || 'file';
  const filename = ext ? `${stem}.${ext}` : stem;

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      'Content-Type': contentType,
      'Content-Disposition': `inline; filename="${filename}"`,
      'Cache-Control': 'public, max-age=86400',
      'Access-Control-Allow-Origin': '*',
    },
  });
}

export default {
  async fetch(request) {
    const { pathname, searchParams } = new URL(request.url);
    const url = searchParams.get('url');

    if (!url) return new Response('Missing "url" query parameter', { status: 400 });

    let parsed;
    try { parsed = new URL(url); } catch {
      return new Response('Invalid URL', { status: 400 });
    }

    if (pathname === '/pfp') {
      if (!hostAllowed(parsed.hostname, YUNHU_HOSTS))
        return new Response('URL not allowed', { status: 403 });
      return proxyUrl(url, { 'Referer': YUNHU_REFERER });
    }

    if (pathname === '/media') {
      if (!hostAllowed(parsed.hostname, DISCORD_HOSTS))
        return new Response('URL not allowed', { status: 403 });
      return proxyUrl(url);
    }

    return new Response('Not found', { status: 404 });
  },
};
