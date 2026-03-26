/**
 * Cloudflare Worker — Telegram avatar proxy
 *
 * Endpoint:
 *   GET /file/{file_path}
 *     Proxies Telegram Bot API avatar files only.
 *     Only allows paths starting with 'photos/' or 'profile_photos/' and
 *     only serves image files (jpeg, png, gif, webp).
 *
 * Environment variables (set in Cloudflare dashboard):
 *   BOT_TOKEN - Your Telegram bot token
 *
 * Deploy:
 *   1. Create a new Worker in the Cloudflare dashboard and paste this file.
 *   2. Set BOT_TOKEN environment variable in the worker settings.
 *   3. Note the worker URL (e.g. https://tg-avatar-proxy.yourname.workers.dev).
 *   4. Set "avatar_proxy_host" in your telegram instance config to that URL.
 *
 * Example config.json entry:
 *   "telegram": {
 *     "my_tg": {
 *       "bot_token": "...",
 *       "avatar_proxy_host": "https://tg-avatar-proxy.yourname.workers.dev"
 *     }
 *   }
 */

const MIME_EXT = {
  'image/jpeg': 'jpg',
  'image/png':  'png',
  'image/gif':  'gif',
  'image/webp': 'webp',
};

// Only allow image MIME types
const ALLOWED_MIME_TYPES = new Set(Object.keys(MIME_EXT));

// Also allow octet-stream (Telegram sometimes returns this for images)
const OCTET_STREAM = 'application/octet-stream';

// Only allow paths starting with these prefixes (avatar/profile photos)
const ALLOWED_PATH_PREFIXES = [
  'photos/',
  'profile_photos/',
];

export default {
  async fetch(request, env, ctx) {
    const { pathname } = new URL(request.url);
    console.log('Request pathname:', pathname);

    // Only allow /file/ paths
    if (!pathname.startsWith('/file/')) {
      console.log('Path does not start with /file/');
      return new Response('Not found', { status: 404 });
    }

    const botToken = env.BOT_TOKEN || 'set-your-bot-token-here-if-using-snippet';
    console.log('BOT_TOKEN configured:', !!botToken);
    if (!botToken) {
      return new Response('BOT_TOKEN not configured', { status: 500 });
    }

    // Extract file_path from /file/{file_path}
    const filePath = pathname.slice('/file/'.length);
    console.log('Extracted filePath:', filePath);
    if (!filePath) {
      return new Response('Missing file path', { status: 400 });
    }

    // Validate path prefix - only allow avatar/profile photos
    const pathAllowed = ALLOWED_PATH_PREFIXES.some(prefix => filePath.startsWith(prefix));
    console.log('Path allowed:', pathAllowed, 'Prefixes:', ALLOWED_PATH_PREFIXES);
    if (!pathAllowed) {
      return new Response('File type not allowed', { status: 403 });
    }

    // Build Telegram API URL
    const tgUrl = `https://api.telegram.org/file/bot${botToken}/${filePath}`;
    console.log('Telegram API URL:', tgUrl.replace(botToken, '***'));

    try {
      const upstream = await fetch(tgUrl, {
        headers: {
          'User-Agent': 'Mozilla/5.0',
          'X-Robots-Tag': 'none',
        },
      });

      console.log('Upstream response status:', upstream.status);
      if (!upstream.ok) {
        console.log('Upstream error:', upstream.status);
        return new Response(`Telegram API error: ${upstream.status}`, { status: upstream.status });
      }

      let contentType = upstream.headers.get('Content-Type') ?? 'application/octet-stream';
      let mime = contentType.split(';')[0].trim();
      console.log('Content-Type:', contentType, 'MIME:', mime);

      // If MIME is octet-stream, try to infer from file extension
      if (mime === OCTET_STREAM) {
        const extMatch = filePath.match(/\.([^.]+)$/);
        if (extMatch) {
          const ext = extMatch[1].toLowerCase();
          const inferredMime = Object.entries(MIME_EXT).find(([_, e]) => e === ext)?.[0];
          if (inferredMime) {
            mime = inferredMime;
            contentType = inferredMime;
            console.log('Inferred MIME from extension:', mime);
          }
        }
      }

      // Validate MIME type - only allow images
      if (!ALLOWED_MIME_TYPES.has(mime)) {
        console.log('MIME type not allowed:', mime);
        return new Response('File type not allowed', { status: 403 });
      }

      const ext = MIME_EXT[mime];

      // Build filename
      const stem = filePath.split('/').pop().replace(/\.[^.]+$/, '') || 'file';
      const filename = ext ? `${stem}.${ext}` : stem;

      console.log('Serving file:', filename);
      return new Response(upstream.body, {
        status: upstream.status,
        headers: {
          'Content-Type': contentType,
          'Content-Disposition': `inline; filename="${filename}"`,
          'Cache-Control': 'public, max-age=86400',
          'Access-Control-Allow-Origin': '*',
        },
      });
    } catch (error) {
      console.log('Proxy error:', error.message);
      return new Response(`Proxy error: ${error.message}`, { status: 500 });
    }
  },
};
