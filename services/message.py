from dataclasses import dataclass, field


@dataclass
class Attachment:
    """A media attachment carried alongside a NormalizedMessage."""

    type: str  # "image" | "video" | "voice" | "file"
    url: str  # download URL (may be empty when unavailable)
    name: str = ""  # filename hint
    size: int = -1  # bytes; -1 = unknown
    data: bytes | None = None  # pre-fetched bytes; if set, skip URL download


@dataclass
class NormalizedMessage:
    """Platform-agnostic message passed through the bridge."""

    platform: str  # e.g. "napcat", "discord", "telegram"
    instance_id: str  # key as defined in config.json
    channel: dict  # platform-specific channel info
    user: str  # display name of sender
    user_id: str  # platform user ID
    user_avatar: str  # avatar URL (may be empty)
    text: str  # message text content
    attachments: list[Attachment] = field(default_factory=list)
    message_id: str | None = None  # ID of this message on its platform
    reply_parent: str | None = None  # ID of the message being replied to (if any)
    mentions: list[dict] = field(
        default_factory=list
    )  # list of {"id": str, "name": str}
    time: str | None = None
    source_proxy: str | None = None  # proxy URL for downloading attachments from source platform

    def __str__(self):
        l = []
        for i in ('platform', 'instance_id', 'channel', 'user', 'user_id', 'user_avatar', 'text', 'reply_parent', 'time, source_proxy'):
            if hasattr(self, i):
                l.append(f'{i}: {getattr(self, i)!r}')
        if self.attachments:
            l.append(f'attachments: {"|".join(repr(a.name) for a in self.attachments)}')
        if self.mentions:
            l.append(f'mentions: {"|".join(repr(m) for m in self.mentions)}')
        return ', '.join(l)