# Shared media download utility used by all drivers when sending
# attachments to a target platform.
#
# Usage:
#   from services.media import fetch
#   result = await fetch(url, max_bytes=8_000_000)
#   if result:
#       data, content_type = result

import mimetypes

import aiohttp

import services.logger as log

l = log.get_logger()

_DEFAULT_MAX = 10 * 1024 * 1024  # 10 MB

_session: aiohttp.ClientSession | None = None


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


async def fetch(url: str, max_bytes: int = _DEFAULT_MAX) -> tuple[bytes, str] | None:
    """
    Download *url* up to *max_bytes*.

    Sends a HEAD request first to check Content-Length before committing to a
    full download.  Falls back to streaming if the server doesn't support HEAD.

    Returns ``(data, content_type)`` on success, or ``None`` if the file is
    oversized, the URL is empty, or the download fails.
    """
    if not url:
        return None

    session = _get_session()

    try:
        # Pre-flight HEAD to skip obviously oversized files without downloading
        try:
            async with session.head(
                url,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                cl = resp.headers.get("Content-Length")
                if cl and int(cl) > max_bytes:
                    l.debug(f"media.fetch: skipping {url!r} — Content-Length {cl} > {max_bytes}")
                    return None
        except Exception:
            pass  # server doesn't support HEAD; proceed with GET

        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=60)
        ) as resp:
            resp.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.content.iter_chunked(65536):
                total += len(chunk)
                if total > max_bytes:
                    l.debug(f"media.fetch: {url!r} exceeded {max_bytes} bytes, aborting")
                    return None
                chunks.append(chunk)
            return b"".join(chunks), resp.content_type or "application/octet-stream"

    except Exception as e:
        l.error(f"media.fetch failed for {url!r}: {e}")
        return None


async def fetch_attachment(att, max_bytes: int = _DEFAULT_MAX) -> tuple[bytes, str] | None:
    """
    Return ``(bytes, mime)`` for an Attachment.

    If ``att.data`` is already populated (e.g. a locally-loaded face GIF),
    return it directly without any network request.  Otherwise fall back to
    ``fetch(att.url, max_bytes)``.
    """
    if att.data is not None:
        if len(att.data) > max_bytes:
            l.debug(f"media.fetch_attachment: {att.name!r} pre-fetched size {len(att.data)} > {max_bytes}, skipping")
            return None
        mime = mimetypes.guess_type(att.name)[0] or "application/octet-stream"
        return att.data, mime
    return await fetch(att.url, max_bytes)


def filename_for(name: str, content_type: str) -> str:
    """Return a sane filename given an optional hint and a MIME type."""
    _mime_ext = {
        "image/jpeg":  "jpg",
        "image/png":   "png",
        "image/gif":   "gif",
        "image/webp":  "webp",
        "video/mp4":   "mp4",
        "video/webm":  "webm",
        "audio/ogg":   "ogg",
        "audio/mpeg":  "mp3",
        "audio/aac":   "aac",
        "audio/amr":   "amr",
    }
    if name:
        # Platforms like Yunhu CDN serve all images with a .tmp extension.
        # Replace it with an extension derived from the actual MIME type so
        # that receiving platforms (Discord etc.) render the file correctly.
        if name.endswith(".tmp"):
            ext = _mime_ext.get(content_type)
            if ext:
                return name[:-4] + "." + ext
        return name
    _fallback = {
        "image/jpeg":  "photo.jpg",
        "image/png":   "photo.png",
        "image/gif":   "image.gif",
        "image/webp":  "image.webp",
        "video/mp4":   "video.mp4",
        "video/webm":  "video.webm",
        "audio/ogg":   "voice.ogg",
        "audio/mpeg":  "audio.mp3",
        "audio/aac":   "audio.aac",
        "audio/amr":   "voice.amr",
    }
    return _fallback.get(content_type, "attachment.bin")
