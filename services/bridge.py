import re
import uuid
from pathlib import Path
from typing import Callable

import services.util as u
import services.logger as log
import services.config_io as config_io
from services.message import NormalizedMessage
from services.db import msg_db

logger = log.get_logger()

# Config keys whose values are treated as credentials and must never appear in
# outgoing messages.  Matched as substrings against lower-cased key names.
_SENSITIVE_KEY_PATTERNS = (
    "token",
    "secret",
    "password",
    "webhook_url",
    "webhook_path",
    "access_token",
)

# Rich-header tag: <richheader title="..." content="..."/>
_RICHHEADER_RE = re.compile(r"<richheader\b([^/]*)/>", re.IGNORECASE)
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def _parse_richheader(text: str) -> tuple[str, dict | None]:
    """
    Extract a ``<richheader title="..." content="..."/>`` tag from *text*.

    Returns ``(clean_text, attrs_dict)`` where *clean_text* has the tag
    (and any directly adjacent whitespace) stripped.  *attrs_dict* is
    ``None`` when no tag is found.
    """
    m = _RICHHEADER_RE.search(text)
    if not m:
        return text, None
    attrs = dict(_ATTR_RE.findall(m.group(1)))
    clean = (text[: m.start()] + text[m.end() :]).strip()
    return clean, attrs or None


def _collect_sensitive(obj, found: set[str]) -> None:
    """Recursively extract sensitive string values from the config dict."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if (
                isinstance(v, str)
                and v
                and any(p in k.lower() for p in _SENSITIVE_KEY_PATTERNS)
            ):
                found.add(v)
            else:
                _collect_sensitive(v, found)
    elif isinstance(obj, list):
        for item in obj:
            _collect_sensitive(item, found)


class Bridge:
    """
    Core routing engine.

    Drivers register a sender callback via ``register_sender``.
    When a driver receives a message it calls ``on_message``; the bridge
    matches it against every rule and calls the appropriate sender(s).
    """

    def __init__(self):
        self._rules: list[dict] = []
        self._senders: dict[str, Callable] = {}
        self._sensitive: frozenset[str] = frozenset()
        self.strict_echo_match: bool = False

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def load_rules(self):
        # Try to find rules file in supported formats
        rules_path = config_io.find_rules(Path(u.get_data_path()))
        if rules_path is None:
            logger.warning("No rules file found")
            self._rules = []
            return

        data = config_io.load_config(rules_path)
        self._rules = data.get("rules", [])
        logger.info(f"Loaded {len(self._rules)} bridge rule(s) from {rules_path.name}")

    def _should_skip_echo(
        self, target_id: str, target_channel: dict, msg: NormalizedMessage
    ) -> bool:
        """Determine if we should skip sending to avoid echo.

        Returns True if the message should be skipped based on strict_echo_match configuration.
        """
        if self.strict_echo_match:
            # Strict mode: skip only if both instance_id and channel match
            return target_id == msg.instance_id and target_channel == msg.channel
        else:
            # Default mode: skip if either instance_id or channel matches
            return target_id == msg.instance_id or target_channel == msg.channel

    def load_sensitive_values(self, config: dict):
        found: set[str] = set()
        _collect_sensitive(config, found)
        self._sensitive = frozenset(found)
        log.register_sensitive(self._sensitive)
        logger.info(
            f"Loaded {len(self._sensitive)} sensitive value(s) for leak detection"
        )

    def register_sender(self, instance_id: str, send_func: Callable):
        self._senders[instance_id] = send_func
        logger.debug(f"Registered sender for instance: {instance_id}")

    async def _handle_bind_command(self, msg: NormalizedMessage):
        """Generate a 6-digit binding code for the user."""
        import random

        code = f"{random.randint(100000, 999999)}"
        msg_db().create_binding_code(code, msg.instance_id, msg.user_id)

        sender = self._senders.get(msg.instance_id)
        if sender:
            try:
                await sender(
                    msg.channel,
                    f"Your binding code is: `{code}` (valid for 5 mins). Type `/confirm {code}` on the other platform to link accounts.",
                )
            except Exception as e:
                logger.error(f"Failed to send bind code back: {e}")

    async def _handle_confirm_command(self, msg: NormalizedMessage):
        """Confirm a binding code from another platform."""
        parts = msg.text.split()
        if len(parts) < 2:
            sender = self._senders.get(msg.instance_id)
            if sender:
                await sender(msg.channel, "Usage: `/confirm <code>`")
            return

        code = parts[1]
        success = msg_db().consume_binding_code(code, msg.instance_id, msg.user_id)

        sender = self._senders.get(msg.instance_id)
        if sender:
            if success:
                await sender(
                    msg.channel,
                    "✅ Account successfully linked! Mentions will now target you correctly across platforms.",
                )
            else:
                await sender(msg.channel, "❌ Invalid or expired binding code.")

    async def _handle_rm_command(self, msg: NormalizedMessage):
        """Remove account bindings for the user."""
        parts = msg.text.split()
        target_inst = parts[1] if len(parts) > 1 else None

        success = msg_db().remove_user_binding(
            msg.instance_id, msg.user_id, target_inst
        )
        sender = self._senders.get(msg.instance_id)
        if sender:
            if success:
                if target_inst:
                    await sender(
                        msg.channel,
                        f"🗑️ The binding for `{target_inst}` has been removed.",
                    )
                else:
                    await sender(
                        msg.channel, "🗑️ All your account bindings have been removed."
                    )
            else:
                if target_inst:
                    await sender(
                        msg.channel,
                        f"❓ No binding found for `{target_inst}` in your account group.",
                    )
                else:
                    await sender(
                        msg.channel, "❓ You don't have any active account bindings."
                    )

    async def _handle_list_command(self, msg: NormalizedMessage):
        """List all accounts linked to the user's global identity."""
        bindings = msg_db().get_all_bindings(msg.instance_id, msg.user_id)
        sender = self._senders.get(msg.instance_id)
        if sender:
            if not bindings:
                await sender(
                    msg.channel, "❓ You don't have any active account bindings."
                )
                return

            lines = ["🔗 **Linked Accounts:**"]
            for inst, uid in bindings:
                name = msg_db().get_user_name(inst, uid) or "Unknown"
                current = (
                    " (Current)"
                    if inst == msg.instance_id and uid == msg.user_id
                    else ""
                )
                lines.append(f"- `{inst}`: {name} (`{uid}`){current}")

            await sender(msg.channel, "\n".join(lines))

    # ------------------------------------------------------------------
    # Message routing
    # ------------------------------------------------------------------

    async def on_message(self, msg: NormalizedMessage):
        logger.debug(
            f"on_message: platform={msg.platform} instance={msg.instance_id} "
            f"channel={msg.channel} user={msg.user!r} text={msg.text!r}"
        )
        # Handle internal commands
        if msg.text.startswith("/bind"):
            await self._handle_bind_command(msg)
            return
        if msg.text.startswith("/confirm"):
            await self._handle_confirm_command(msg)
            return
        if msg.text.startswith("/rm"):
            await self._handle_rm_command(msg)
            return
        if msg.text.startswith("/list"):
            await self._handle_list_command(msg)
            return

        # Save sender's user mapping
        if msg.user_id:
            msg_db().save_user(msg.instance_id, msg.user_id, msg.user)

        # Generate or resolve bridge_id for the incoming message
        bridge_id = str(uuid.uuid4())
        if msg.message_id:
            msg_db().save_mapping(
                bridge_id, msg.instance_id, str(msg.channel), msg.message_id
            )

        reply_bridge_id = None
        if msg.reply_parent:
            reply_bridge_id = msg_db().get_bridge_id(msg.instance_id, msg.reply_parent)

        for rule in self._rules:
            if rule.get("type") == "connect":
                matched = self._matches_channel(msg, rule.get("channels", {}))
                logger.debug(f"Rule connect match for {msg.instance_id}: {matched}")
                if matched:
                    await self._dispatch_connect(msg, rule, bridge_id, reply_bridge_id)
            else:
                if self._matches_from(msg, rule.get("from", {})):
                    await self._dispatch(msg, rule, bridge_id, reply_bridge_id)

    def _matches_channel(self, msg: NormalizedMessage, channels: dict) -> bool:
        """Return True if *msg* originates from one of the channels in a connect rule.

        Only keys that are present in msg.channel are compared — other keys in
        the channel config block (e.g. webhook_url, msg_format) are skipped so
        they do not interfere with address matching.
        """
        if msg.instance_id not in channels:
            return False
        rule_ch = channels[msg.instance_id]
        for key, expected in rule_ch.items():
            if key in ("msg",):  # reserved — not a channel address field
                continue
            if key not in msg.channel:
                continue  # config-only field (webhook_url, msg_format, …) — skip
            if str(msg.channel[key]) != str(expected):
                logger.debug(
                    f"Channel match fail for {msg.instance_id}: "
                    f"{key}={msg.channel[key]!r} != expected {expected!r}"
                )
                return False
        return True

    def _matches_from(self, msg: NormalizedMessage, from_cfg: dict) -> bool:
        """Return True if *msg* matches the ``from`` block of a forward rule."""
        if msg.instance_id not in from_cfg:
            return False
        for key, expected in from_cfg[msg.instance_id].items():
            if key not in msg.channel:
                continue
            if str(msg.channel[key]) != str(expected):
                return False
        return True

    def _build_formatted(
        self, msg: NormalizedMessage, msg_cfg: dict
    ) -> tuple[str, dict]:
        """Return (formatted_text, extra_kwargs) for a given msg config block."""
        fmt = msg_cfg.get("msg_format", "{msg}")
        ctx = {
            "platform": msg.platform,
            "instance_id": msg.instance_id,
            "from": msg.instance_id,
            "user": msg.user,
            "username": msg.user,
            "user_id": msg.user_id,
            "user_avatar": msg.user_avatar,
            "msg": msg.text,
            "time": msg.time,
        }
        try:
            formatted = fmt.format(**ctx)
        except KeyError as e:
            logger.warning(f"msg_format missing key {e}; using raw text")
            formatted = msg.text

        formatted, rich_header = _parse_richheader(formatted)

        extra: dict = {}
        if rich_header is not None:
            rich_header["avatar"] = msg.user_avatar
            extra["rich_header"] = rich_header
        for k, v in msg_cfg.items():
            if k == "msg_format":
                continue
            try:
                extra[k] = v.format(**ctx) if isinstance(v, str) else v
            except KeyError:
                extra[k] = v

        return formatted, extra

    def _is_sensitive(self, text: str) -> bool:
        return bool(self._sensitive) and any(s in text for s in self._sensitive)

    async def _dispatch(
        self,
        msg: NormalizedMessage,
        rule: dict,
        bridge_id: str,
        reply_bridge_id: str | None = None,
    ):
        formatted, extra = self._build_formatted(msg, rule.get("msg", {}))

        for target_id, target_channel in rule.get("to", {}).items():
            # Skip echo based on strict_echo_match configuration
            if self._should_skip_echo(target_id, target_channel, msg):
                continue

            if self._is_sensitive(formatted):
                logger.warning(
                    f"Message to '{target_id}' blocked: text contains a sensitive "
                    f"value from config (token/secret/webhook). Possible credential leak."
                )
                continue

            sender = self._senders.get(target_id)
            if sender is None:
                logger.warning(f"No sender registered for instance '{target_id}'")
                continue

            # Resolve target reply ID
            target_reply_id = None
            if reply_bridge_id:
                target_reply_id = msg_db().get_platform_msg_id(
                    reply_bridge_id, target_id, str(target_channel)
                )
                if target_reply_id:
                    extra["reply_to_id"] = target_reply_id

            # Resolve target mentions
            target_mentions = []
            for m in msg.mentions:
                # 1. Try explicit binding first
                target_uid = msg_db().get_bound_user_id(
                    msg.instance_id, m["id"], target_id
                )
                # 2. Fall back to display name match
                if not target_uid:
                    target_uid = msg_db().get_user_id_by_name(target_id, m["name"])

                if target_uid:
                    target_mentions.append({"id": target_uid, "name": m["name"]})
            if target_mentions:
                extra["mentions"] = target_mentions

            try:
                new_msg_id = await sender(
                    target_channel, formatted, attachments=msg.attachments, **extra
                )
                if new_msg_id:
                    msg_db().save_mapping(
                        bridge_id, target_id, str(target_channel), str(new_msg_id)
                    )
            except Exception as e:
                logger.error(f"Failed to send to '{target_id}': {e}")

    async def _dispatch_connect(
        self,
        msg: NormalizedMessage,
        rule: dict,
        bridge_id: str,
        reply_bridge_id: str | None = None,
    ):
        """Fan-out to every channel in the connect rule except the source."""
        global_msg_cfg = rule.get("msg", {})

        for target_id, target_cfg in rule.get("channels", {}).items():
            # Strip the reserved "msg" key to get the bare channel address dict
            target_channel = {k: v for k, v in target_cfg.items() if k != "msg"}

            # Skip echo based on strict_echo_match configuration
            if self._should_skip_echo(target_id, target_channel, msg):
                logger.debug(f"Skipping echo to {target_id}")
                continue

            logger.debug(f"Dispatching to {target_id} channel={target_channel}")

            # Per-target msg overrides the global msg (target wins on conflict)
            merged_msg_cfg = {**global_msg_cfg, **target_cfg.get("msg", {})}
            formatted, extra = self._build_formatted(msg, merged_msg_cfg)

            if self._is_sensitive(formatted):
                logger.warning(
                    f"Message to '{target_id}' blocked: text contains a sensitive "
                    f"value from config (token/secret/webhook). Possible credential leak."
                )
                continue

            sender = self._senders.get(target_id)
            if sender is None:
                logger.warning(f"No sender registered for instance '{target_id}'")
                continue

            # Resolve target reply ID
            target_reply_id = None
            if reply_bridge_id:
                target_reply_id = msg_db().get_platform_msg_id(
                    reply_bridge_id, target_id, str(target_channel)
                )
                if target_reply_id:
                    extra["reply_to_id"] = target_reply_id

            # Resolve target mentions
            target_mentions = []
            for m in msg.mentions:
                # 1. Try explicit binding first
                target_uid = msg_db().get_bound_user_id(
                    msg.instance_id, m["id"], target_id
                )
                # 2. Fall back to display name match
                if not target_uid:
                    target_uid = msg_db().get_user_id_by_name(target_id, m["name"])

                if target_uid:
                    target_mentions.append({"id": target_uid, "name": m["name"]})
            if target_mentions:
                extra["mentions"] = target_mentions

            try:
                new_msg_id = await sender(
                    target_channel, formatted, attachments=msg.attachments, **extra
                )
                if new_msg_id:
                    msg_db().save_mapping(
                        bridge_id, target_id, str(target_channel), str(new_msg_id)
                    )
            except Exception as e:
                logger.error(f"Failed to send to '{target_id}': {e}")


# Shared singleton used by all drivers
bridge = Bridge()
