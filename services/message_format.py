"""Shared message-formatting helpers used across drivers."""

import html
import re


_RICHHEADER_RE = re.compile(r"<richheader\b(.*?)/>", re.IGNORECASE | re.DOTALL)
_RICHHEADER_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def parse_richheader_tag(text: str) -> tuple[str, dict | None]:
    """Extract a ``<richheader title=\"...\" content=\"...\"/>`` tag from *text*.

    Returns ``(clean_text, attrs_dict)`` where *clean_text* has the tag
    (and any directly adjacent whitespace) stripped.  *attrs_dict* is
    ``None`` when no tag is found.
    """
    m = _RICHHEADER_RE.search(text)
    if not m:
        return text, None
    attrs = dict(_RICHHEADER_ATTR_RE.findall(m.group(1)))
    clean = (text[: m.start()] + text[m.end() :]).strip()
    return clean, attrs or None


def apply_rich_header(
    text: str,
    rich_header: dict | None,
    style: str = "plain",
) -> str:
    """Prepend a rich header to *text* in a platform-appropriate markup style.

    Styles:
      - ``"plain"`` → ``[Title · Content]``
      - ``"markdown"`` → ``**Title** · *Content*``
      - ``"google_chat"`` → ``*Title* · _Content_``
    """
    if not rich_header:
        return text
    t = rich_header.get("title", "") or ""
    c = rich_header.get("content", "") or ""

    if style == "plain":
        prefix = f"[{t}" + (f" \u00b7 {c}" if c else "") + "]"
    elif style == "markdown":
        prefix = f"**{t}**" + (f" \u00b7 *{c}*" if c else "")
    elif style == "google_chat":
        prefix = f"*{t}*" + (f" \u00b7 _{c}_" if c else "")
    else:
        prefix = f"[{t}" + (f" \u00b7 {c}" if c else "") + "]"

    return f"{prefix}\n{text}" if text else prefix


def telegram_richheader_html(title: str, content: str) -> str:
    """Render a rich header as a Telegram HTML snippet."""
    t = html.escape(title)
    c = html.escape(content)
    return f"<b><code>{t}</code></b>" + (
        f" \u00b7 <i><code>{c}</code></i>" if c else ""
    )
