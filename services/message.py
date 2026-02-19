from dataclasses import dataclass, field


@dataclass
class Attachment:
    """A media attachment carried alongside a NormalizedMessage."""
    type: str      # "image" | "video" | "voice" | "file"
    url: str       # download URL (may be empty when unavailable)
    name: str = "" # filename hint
    size: int = -1 # bytes; -1 = unknown
    data: bytes | None = None  # pre-fetched bytes; if set, skip URL download


@dataclass
class NormalizedMessage:
    """Platform-agnostic message passed through the bridge."""
    platform: str       # e.g. "napcat", "discord", "telegram"
    instance_id: str    # key as defined in config.json
    channel: dict       # platform-specific channel info
    user: str           # display name of sender
    user_id: str        # platform user ID
    user_avatar: str    # avatar URL (may be empty)
    text: str           # message text content
    attachments: list[Attachment] = field(default_factory=list)
