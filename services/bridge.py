import asyncio
import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

import services.logger as log
from services import config, cqface
from services.db import msg_db
from services.message import NormalizedMessage

logger = log.get_logger()

# Config keys whose values are treated as credentials and must never appear in
# outgoing messages.  Matched as substrings against lower-cased key names.
_SENSITIVE_KEY_PATTERNS = (
    "token",
    "secret",
    "password",
    "webhook_url",
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
        self._senders: dict[str, tuple[str | None, Callable]] = {}
        self._sensitive: frozenset[str] = frozenset()
        self.strict_echo_match: bool = False
        self.command_prefix: str = "nb"

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def load_rules(self):
        # Load rules and normalize each rule with a stable id
        rules, rules_path = config.load_rules_with_ids()
        if rules_path is None:
            logger.warning("No rules file found")
            self._rules = []
            return

        self._rules = rules
        logger.info(f"Loaded {len(self._rules)} bridge rule(s) from {rules_path.name}")

    def _build_bridge_id(self, rule_id: str, msg: NormalizedMessage) -> str:
        """Build a deterministic bridge id based on rule id and message fingerprint."""
        if msg.message_id:
            return f"{rule_id}:{msg.instance_id}:{msg.message_id}"

        # Some drivers may not provide message_id; fallback to a stable fingerprint.
        fingerprint_obj = {
            "instance_id": msg.instance_id,
            "channel": msg.channel,
            "user_id": msg.user_id,
            "text": msg.text,
            "time": msg.time,
        }
        raw = json.dumps(
            fingerprint_obj,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        )
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"{rule_id}:{digest}"

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
        platform = None
        owner = getattr(send_func, "__self__", None)
        if owner is not None:
            platform = getattr(owner, "platform_name", None)
            if not platform:
                module = owner.__class__.__module__
                if module.startswith("drivers."):
                    platform = module.split(".", 1)[1]

        self._senders[instance_id] = (platform, send_func)
        logger.debug(f"Registered sender for instance: {instance_id}")

    def _get_command_prefix(self) -> str:
        prefix = (self.command_prefix or "nb").strip().lstrip("/")
        return prefix or "nb"

    def _get_command_help(self) -> str:
        prefix = self._get_command_prefix()
        return (
            f"Usage: `/{prefix} bind setup`, `/{prefix} bind confirm <code>`, "
            f"`/{prefix} bind rm [instance_id]`, `/{prefix} bind list`, `/ping <target>`"
        )

    def _parse_ping_command(self, text: str) -> str | None:
        parts = text.strip().split(maxsplit=1)
        if not parts:
            return None
        command = parts[0]
        if not command.startswith("/"):
            return None

        root = command[1:].split("@", 1)[0].lower()
        if root != "ping":
            return None

        if len(parts) < 2:
            return ""

        nickname = parts[1].strip().lstrip("@").strip()
        return nickname

    def _parse_internal_command(self, text: str) -> tuple[str, list[str]] | None:
        parts = text.split()
        if len(parts) < 2 or not parts[0].startswith("/"):
            return None

        root = parts[0][1:]
        if root != self._get_command_prefix():
            return None

        return parts[1].lower(), parts[2:]

    async def _handle_bind_setup_command(self, msg: NormalizedMessage):
        """Generate a 6-digit binding code for the user."""
        import random

        code = f"{random.randint(100000, 999999)}"
        msg_db().create_binding_code(code, msg.instance_id, msg.user_id)

        sender_info = self._senders.get(msg.instance_id)
        if sender_info:
            _, sender = sender_info
            try:
                prefix = self._get_command_prefix()
                await sender(
                    msg.channel,
                    f"Your binding code is: `{code}` (valid for 5 mins). Type `/{prefix} bind confirm {code}` on the other platform to link accounts.",
                )
            except Exception as e:
                logger.error(f"Failed to send bind code back: {e}")

    async def _handle_bind_confirm_command(
        self, msg: NormalizedMessage, code: str | None
    ):
        """Confirm a binding code from another platform."""
        if not code:
            sender_info = self._senders.get(msg.instance_id)
            if sender_info:
                _, sender = sender_info
                prefix = self._get_command_prefix()
                await sender(msg.channel, f"Usage: `/{prefix} bind confirm <code>`")
            return

        success = msg_db().consume_binding_code(code, msg.instance_id, msg.user_id)

        sender_info = self._senders.get(msg.instance_id)
        if sender_info:
            _, sender = sender_info
            if success:
                await sender(
                    msg.channel,
                    "✅ Account successfully linked! Mentions will now target you correctly across platforms.",
                )
            else:
                await sender(msg.channel, "❌ Invalid or expired binding code.")

    async def _handle_bind_rm_command(
        self, msg: NormalizedMessage, target_inst: str | None
    ):
        """Remove account bindings for the user."""
        success = msg_db().remove_user_binding(
            msg.instance_id, msg.user_id, target_inst
        )
        sender_info = self._senders.get(msg.instance_id)
        if sender_info:
            _, sender = sender_info
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

    async def _handle_bind_list_command(self, msg: NormalizedMessage):
        """List all accounts linked to the user's global identity."""
        bindings = msg_db().get_all_bindings(msg.instance_id, msg.user_id)
        sender_info = self._senders.get(msg.instance_id)
        if sender_info:
            _, sender = sender_info
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
        logger.info(f"on_message: {msg!s}")
        ping_nickname = self._parse_ping_command(msg.text)
        if ping_nickname is not None:
            if not ping_nickname:
                sender_info = self._senders.get(msg.instance_id)
                if sender_info:
                    _, sender = sender_info
                    await sender(msg.channel, "Usage: `/ping <nickname>`")
                return

            msg.text = f"@{ping_nickname}"
            msg.mentions = [{"id": "", "name": ping_nickname}]

        # Handle internal commands
        command = self._parse_internal_command(msg.text)
        if command is not None:
            action, args = command
            if action != "bind":
                return

            subcommand = args[0].lower() if args else ""
            match subcommand:
                case "setup":
                    await self._handle_bind_setup_command(msg)
                    return
                case "confirm":
                    await self._handle_bind_confirm_command(
                        msg, args[1] if len(args) > 1 else None
                    )
                    return
                case "rm":
                    await self._handle_bind_rm_command(
                        msg, args[1] if len(args) > 1 else None
                    )
                    return
                case "list":
                    await self._handle_bind_list_command(msg)
                    return

            sender_info = self._senders.get(msg.instance_id)
            if sender_info:
                _, sender = sender_info
                await sender(msg.channel, self._get_command_help())
            return

        # Save sender's user mapping
        if msg.user_id:
            if msg.instance_id == "qq":
                # QQ users are better addressed by qid; fallback to QQ number.
                display_name = (msg.username or msg.user_id).strip() or msg.user_id
            else:
                # Default ping target matching prefers stable username over nickname.
                display_name = (msg.username or msg.user).strip() or msg.user_id
            msg_db().save_user(msg.instance_id, msg.user_id, display_name)

        reply_bridge_id = None
        if msg.reply_parent:
            reply_bridge_id = msg_db().get_bridge_id(msg.instance_id, msg.reply_parent)
            if reply_bridge_id is None:
                logger.debug(
                    f"Reply parent mapping not found: instance={msg.instance_id} "
                    f"parent={msg.reply_parent}"
                )

        for rule in self._rules:
            rule_id = str(rule.get("id", ""))
            if not rule_id:
                rule_id = config.stable_rule_hash(rule)

            bridge_id = self._build_bridge_id(rule_id, msg)
            if rule.get("type") == "connect":
                matched = self._matches_channel(msg, rule.get("channels", {}))
                # logger.debug(f"Rule connect match for {msg.instance_id}: {matched}")
                if matched:
                    if msg.message_id:
                        msg_db().save_mapping(
                            bridge_id, msg.instance_id, msg.channel, msg.message_id
                        )
                    await self._dispatch_connect(msg, rule, bridge_id, reply_bridge_id)
            else:
                if self._matches_from(msg, rule.get("from", {})):
                    if msg.message_id:
                        msg_db().save_mapping(
                            bridge_id, msg.instance_id, msg.channel, msg.message_id
                        )
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
                continue  # config-only field (webhook_url, msg_format, ...) — skip
            if str(msg.channel[key]) != str(expected):
                return False
        logger.debug(f"Channel match success for {msg.instance_id}: {key}={expected!r}")
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
        self, msg: NormalizedMessage, msg_cfg: dict, is_webhook: bool = False
    ) -> tuple[str, dict]:
        """Return (formatted_text, extra_kwargs) for a given msg config block."""
        # Choose format based on send path
        if is_webhook and "webhook_msg_format" in msg_cfg:
            fmt = msg_cfg["webhook_msg_format"]
        elif not is_webhook and "bot_msg_format" in msg_cfg:
            fmt = msg_cfg["bot_msg_format"]
        else:
            fmt = msg_cfg.get(
                "msg_format",
                '<richheader title="{user}" content="{user_id} ({platform})"/> \n{msg}',
            )
        # Format username with @ prefix if it exists
        username_value = getattr(msg, "username", "")
        if username_value and not username_value.startswith("@"):
            username_value = f"@{username_value}"
        # If username is empty, fallback to user_id
        if not username_value:
            username_value = msg.user_id

        ctx = {
            "platform": msg.platform,
            "instance_id": msg.instance_id,
            "from": msg.instance_id,
            "user": msg.user,
            "user_id": msg.user_id,
            "user_avatar": msg.user_avatar,
            "msg": msg.text,
            "time": msg.time,
            "username": username_value,
            "nickname": getattr(msg, "nickname", ""),
            "source_mentioned_self": getattr(msg, "source_mentioned_self", None),
        }
        try:
            formatted = fmt.format(**ctx)
        except KeyError as e:
            logger.warning(f"msg_format missing key {e}; using raw text")
            formatted = msg.text

        formatted, rich_header = _parse_richheader(formatted)

        extra: dict = {}
        # Always pass the original message context to extra for drivers to use
        extra.update(ctx)
        # Pass source proxy for downloading attachments from source platform
        extra["source_proxy"] = msg.source_proxy
        if rich_header is not None:
            rich_header["avatar"] = msg.user_avatar
            extra["rich_header"] = rich_header
        for k, v in msg_cfg.items():
            # Skip msg_format and webhook/bot-specific format keys - they will be handled by the driver
            if k in ("msg_format", "webhook_msg_format", "bot_msg_format"):
                # Pass these format strings to extra without formatting - driver will handle them
                extra[k] = v
                continue
            try:
                extra[k] = v.format(**ctx) if isinstance(v, str) else v
            except KeyError:
                extra[k] = v

        return formatted, extra

    def _is_sensitive(self, text: str) -> bool:
        return bool(self._sensitive) and any(s in text for s in self._sensitive)

    def _normalize_target_cqface(
        self, target_platform: str | None, text: str, extra: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        if target_platform == "discord":
            return text, dict(extra)

        return cqface.replace_cqface_tokens(text), cqface.replace_cqface_tokens_in_obj(
            extra
        )

    def _resolve_target_mention_user_id(
        self, msg: NormalizedMessage, mention: dict[str, Any], target_instance: str
    ) -> str | None:
        mention_id = str(mention.get("id", "") or "")
        mention_name = str(mention.get("name", "") or "").strip()

        if mention_id:
            target_uid = msg_db().get_bound_user_id(
                msg.instance_id, mention_id, target_instance
            )
            if target_uid:
                return target_uid

        if target_instance == "qq":
            # QQ target addressing uses numeric QQ id or qid alias.
            if mention_id.isdigit():
                return mention_id
            if mention_name.isdigit():
                return mention_name
            if mention_name:
                return msg_db().get_user_id_by_name(target_instance, mention_name)
            return None

        if mention_name:
            return msg_db().get_user_id_by_name(target_instance, mention_name)

        return None

    async def _dispatch(
        self,
        msg: NormalizedMessage,
        rule: dict,
        bridge_id: str,
        reply_bridge_id: str | None = None,
    ):
        # Check if any target uses webhook
        is_webhook = any("webhook_url" in ch for ch in rule.get("to", {}).values())
        formatted, extra = self._build_formatted(
            msg, rule.get("msg", {}), is_webhook=is_webhook
        )

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

            sender_info = self._senders.get(target_id)
            if sender_info is None:
                logger.warning(f"No sender registered for instance '{target_id}'")
                continue
            target_platform, sender = sender_info

            formatted_out, extra_out = self._normalize_target_cqface(
                target_platform, formatted, extra
            )

            # Resolve target reply ID
            target_reply_id = None
            if reply_bridge_id:
                target_reply_id = msg_db().get_platform_msg_id(
                    reply_bridge_id, target_id, target_channel
                )
                if target_reply_id:
                    extra_out["reply_to_id"] = target_reply_id
                    logger.debug(
                        f"Reply mapping resolved for {target_id}: "
                        f"bridge_id={reply_bridge_id} -> {target_reply_id}"
                    )
                else:
                    logger.debug(
                        f"Reply mapping missing for {target_id}: "
                        f"bridge_id={reply_bridge_id}, channel={target_channel}"
                    )

            # Resolve target mentions
            target_mentions = []
            source_self_mention_names: list[str] = []
            source_self_id = str(getattr(msg, "source_self_id", "") or "")
            for m in msg.mentions:
                target_uid = self._resolve_target_mention_user_id(msg, m, target_id)
                if target_uid:
                    target_mentions.append({"id": target_uid, "name": m["name"]})
                    continue

                # Fallback: source @self_id (bot) mention can be converted by
                # target drivers that know their own bot account id.
                m_id = str(m.get("id", "") or "")
                m_name = str(m.get("name", "") or "").strip()
                if source_self_id and m_id == source_self_id and m_name:
                    source_self_mention_names.append(m_name)
            if target_mentions:
                extra_out["mentions"] = target_mentions
            if source_self_mention_names:
                extra_out["source_self_mention_names"] = list(
                    dict.fromkeys(source_self_mention_names)
                )

            try:
                new_msg_id = await sender(
                    target_channel,
                    formatted_out,
                    attachments=msg.attachments,
                    **extra_out,
                )
                if new_msg_id:
                    msg_db().save_mapping(
                        bridge_id, target_id, target_channel, str(new_msg_id)
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
                # logger.debug(f"Skipping echo to {target_id}")
                continue

            logger.debug(f"Dispatching to {target_id} channel={target_channel}")

            # Per-target msg overrides the global msg (target wins on conflict)
            merged_msg_cfg = {**global_msg_cfg, **target_cfg.get("msg", {})}

            # Ensure webhook_url is passed to extra if present in target_cfg
            is_webhook = "webhook_url" in target_cfg
            if is_webhook:
                merged_msg_cfg["webhook_url"] = target_cfg["webhook_url"]

            formatted, extra = self._build_formatted(
                msg, merged_msg_cfg, is_webhook=is_webhook
            )

            if self._is_sensitive(formatted):
                logger.warning(
                    f"Message to '{target_id}' blocked: text contains a sensitive "
                    f"value from config (token/secret/webhook). Possible credential leak."
                )
                continue

            sender_info = self._senders.get(target_id)
            if sender_info is None:
                logger.warning(f"No sender registered for instance '{target_id}'")
                continue
            target_platform, sender = sender_info

            formatted_out, extra_out = self._normalize_target_cqface(
                target_platform, formatted, extra
            )

            # Resolve target reply ID
            target_reply_id = None
            if reply_bridge_id:
                target_reply_id = msg_db().get_platform_msg_id(
                    reply_bridge_id, target_id, target_channel
                )
                if target_reply_id:
                    extra_out["reply_to_id"] = target_reply_id
                    logger.debug(
                        f"Reply mapping resolved for {target_id}: "
                        f"bridge_id={reply_bridge_id} -> {target_reply_id}"
                    )
                else:
                    logger.debug(
                        f"Reply mapping missing for {target_id}: "
                        f"bridge_id={reply_bridge_id}, channel={target_channel}"
                    )

            # Resolve target mentions
            target_mentions = []
            source_self_mention_names: list[str] = []
            source_self_id = str(getattr(msg, "source_self_id", "") or "")
            for m in msg.mentions:
                target_uid = self._resolve_target_mention_user_id(msg, m, target_id)
                if target_uid:
                    target_mentions.append({"id": target_uid, "name": m["name"]})
                    continue

                # Fallback: source @self_id (bot) mention can be converted by
                # target drivers that know their own bot account id.
                m_id = str(m.get("id", "") or "")
                m_name = str(m.get("name", "") or "").strip()
                if source_self_id and m_id == source_self_id and m_name:
                    source_self_mention_names.append(m_name)
            if target_mentions:
                extra_out["mentions"] = target_mentions
            if source_self_mention_names:
                extra_out["source_self_mention_names"] = list(
                    dict.fromkeys(source_self_mention_names)
                )

            try:
                new_msg_id = await sender(
                    target_channel,
                    formatted_out,
                    attachments=msg.attachments,
                    **extra_out,
                )
                if new_msg_id:
                    msg_db().save_mapping(
                        bridge_id, target_id, target_channel, str(new_msg_id)
                    )
            except asyncio.CancelledError:
                logger.info(f"Message dispatch cancelled during send to {target_id}")
                # Don't return - continue to process other targets
                continue
            except Exception:
                logger.exception(f"Failed to send to '{target_id}")
                return


# Shared singleton used by all drivers
bridge = Bridge()
