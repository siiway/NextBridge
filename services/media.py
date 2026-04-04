# Shared media download utility used by all drivers when sending
# attachments to a target platform.
#
# Usage:
#   from services.media import fetch
#   result = await fetch(url, max_bytes=8_000_000)
#   if result:
#       data, content_type = result

import mimetypes
import asyncio
import shutil

import aiohttp
from aiohttp_socks import ProxyConnector

import services.logger as log

logger = log.get_logger()

_DEFAULT_MAX = 10 * 1024 * 1024  # 10 MB

_sessions: dict[str | None, aiohttp.ClientSession] = {}
_ffmpeg_available: bool | None = None


def _looks_like_amr(data: bytes) -> bool:
    # AMR-NB/AMR-WB magic headers
    return data.startswith(b"#!AMR\n") or data.startswith(b"#!AMR-WB\n")


def _is_amr_attachment(att, mime: str, data: bytes) -> bool:
    if mime == "audio/amr":
        return True
    if att.name.lower().endswith(".amr"):
        return True
    return _looks_like_amr(data)


async def _convert_amr_to_ogg(data: bytes) -> tuple[bytes, str] | None:
    global _ffmpeg_available

    if _ffmpeg_available is False:
        return None
    if _ffmpeg_available is None:
        _ffmpeg_available = shutil.which("ffmpeg") is not None
        if not _ffmpeg_available:
            logger.warning("media: ffmpeg not found; AMR audio will be forwarded as-is")
            return None

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-c:a",
            "libopus",
            "-f",
            "ogg",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(data), timeout=25)
        if proc.returncode != 0 or not stdout:
            err = stderr.decode(errors="ignore").strip()
            logger.warning(f"media: ffmpeg AMR->OGG conversion failed: {err or proc.returncode}")
            return None
        return stdout, "audio/ogg"
    except TimeoutError:
        logger.warning("media: ffmpeg AMR->OGG conversion timed out")
        return None
    except Exception as e:
        logger.warning(f"media: ffmpeg AMR->OGG conversion error: {e}")
        return None


def _get_session(proxy: str | None = None) -> aiohttp.ClientSession:
    global _sessions

    if proxy in _sessions and not _sessions[proxy].closed:
        # session exists
        return _sessions[proxy]

    # new session
    connector = ProxyConnector.from_url(proxy, rdns=True) if proxy else None
    session = aiohttp.ClientSession(connector=connector)
    _sessions[proxy] = session
    logger.debug(
        f"New {'proxy' if proxy else 'direct'} session {session}{f'({session._default_proxy})' if proxy else ''}"
    )
    return session


async def close_all_sessions() -> None:
    """
    Close all tracked aiohttp.ClientSession instances and clear the session cache.

    This should be called on application shutdown to avoid leaking open
    connections when multiple per-proxy sessions have been created.
    """
    global _sessions

    # Take a snapshot to avoid mutation-while-iterating issues
    sessions = list(_sessions.values())
    _sessions.clear()

    for session in sessions:
        if not session.closed:
            try:
                await session.close()
            except Exception as e:
                # Log and continue closing remaining sessions
                logger.exception(
                    f"Error while closing aiohttp ClientSession {session} in services.media: {e}"
                )


async def fetch(
    url: str, max_bytes: int = _DEFAULT_MAX, proxy: str | None = None
) -> tuple[bytes, str] | None:
    """
    Download *url* up to *max_bytes*.

    Sends a HEAD request first to check Content-Length before committing to a
    full download.  Falls back to streaming if the server doesn't support HEAD.

    Returns ``(data, content_type)`` on success, or ``None`` if the file is
    oversized, the URL is empty, or the download fails.
    """
    if not url:
        return None

    session = _get_session(proxy=proxy)

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
                    logger.debug(
                        f"media.fetch: skipping {url!r} — Content-Length {cl} > {max_bytes}"
                    )
                    return None
        except Exception:
            pass  # server doesn't support HEAD; proceed with GET

        async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            resp.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.content.iter_chunked(65536):
                total += len(chunk)
                if total > max_bytes:
                    logger.debug(
                        f"media.fetch: {url!r} exceeded {max_bytes} bytes, aborting"
                    )
                    return None
                chunks.append(chunk)
            return b"".join(chunks), resp.content_type or "application/octet-stream"

    except Exception as e:
        logger.error(f"media.fetch failed for {url!r}: {e}")
        return None


async def fetch_attachment(
    att, max_bytes: int = _DEFAULT_MAX, proxy: str | None = None
) -> tuple[bytes, str] | None:
    """
    Return ``(bytes, mime)`` for an Attachment.

    If ``att.data`` is already populated (e.g. a locally-loaded face GIF),
    return it directly without any network request.  Otherwise fall back to
    ``fetch(att.url, max_bytes)``.
    """
    if att.data is not None:
        if len(att.data) > max_bytes:
            logger.debug(
                f"media.fetch_attachment: {att.name!r} pre-fetched size {len(att.data)} > {max_bytes}, skipping"
            )
            return None
        mime = mimetypes.guess_type(att.name)[0] or "application/octet-stream"
        data = att.data
    else:
        result = await fetch(att.url, max_bytes, proxy)
        if not result:
            return None
        data, mime = result

    if att.type == "voice" and _is_amr_attachment(att, mime, data):
        converted = await _convert_amr_to_ogg(data)
        if converted:
            return converted

    return data, mime


def filename_for(name: str, content_type: str) -> str:
    """Return a sane filename given an optional hint and a MIME type."""
    _mime_ext = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/gif": "gif",
        "image/webp": "webp",
        "video/mp4": "mp4",
        "video/webm": "webm",
        "audio/ogg": "ogg",
        "audio/mpeg": "mp3",
        "audio/aac": "aac",
        "audio/amr": "amr",
    }
    if name:
        # Platforms like Yunhu CDN serve all images with a .tmp extension.
        # Replace it with an extension derived from the actual MIME type so
        # that receiving platforms (Discord etc.) render the file correctly.
        if name.endswith(".tmp"):
            ext = _mime_ext.get(content_type)
            if ext:
                return name[:-4] + "." + ext
        # If AMR voice has been transcoded to OGG, keep filename extension aligned
        # so target platforms won't treat it as unsupported AMR.
        if content_type == "audio/ogg" and name.lower().endswith(".amr"):
            return name[:-4] + ".ogg"
        return name
    _fallback = {
        "image/jpeg": "photo.jpg",
        "image/png": "photo.png",
        "image/gif": "image.gif",
        "image/webp": "image.webp",
        "video/mp4": "video.mp4",
        "video/webm": "video.webm",
        "audio/ogg": "voice.ogg",
        "audio/mpeg": "audio.mp3",
        "audio/aac": "audio.aac",
        "audio/amr": "voice.amr",
    }
    return _fallback.get(content_type, "attachment.bin")
