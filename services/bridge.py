import json
from pathlib import Path
from typing import Callable

import services.util as u
import services.logger as log
from services.message import NormalizedMessage

l = log.get_logger()

# Config keys whose values are treated as credentials and must never appear in
# outgoing messages.  Matched as substrings against lower-cased key names.
_SENSITIVE_KEY_PATTERNS = ("token", "secret", "password", "webhook_url")


def _collect_sensitive(obj, found: set[str]) -> None:
    """Recursively extract sensitive string values from the config dict."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v and any(p in k.lower() for p in _SENSITIVE_KEY_PATTERNS):
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

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def load_rules(self):
        rules_path = Path(u.get_data_path()) / "rules.json"
        with open(rules_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._rules = data.get("rules", [])
        l.info(f"Loaded {len(self._rules)} bridge rule(s)")

    def load_sensitive_values(self, config: dict):
        found: set[str] = set()
        _collect_sensitive(config, found)
        self._sensitive = frozenset(found)
        l.info(f"Loaded {len(self._sensitive)} sensitive value(s) for leak detection")

    def register_sender(self, instance_id: str, send_func: Callable):
        self._senders[instance_id] = send_func
        l.debug(f"Registered sender for instance: {instance_id}")

    # ------------------------------------------------------------------
    # Message routing
    # ------------------------------------------------------------------

    async def on_message(self, msg: NormalizedMessage):
        for rule in self._rules:
            if rule.get("type") == "connect":
                if self._matches_channel(msg, rule.get("channels", {})):
                    await self._dispatch_connect(msg, rule)
            else:
                if self._matches_from(msg, rule.get("from", {})):
                    await self._dispatch(msg, rule)

    def _matches_channel(self, msg: NormalizedMessage, channels: dict) -> bool:
        """Return True if *msg* originates from one of the channels in a connect rule."""
        if msg.instance_id not in channels:
            return False
        for key, expected in channels[msg.instance_id].items():
            if key == "msg":  # reserved — not a channel address field
                continue
            if str(msg.channel.get(key, "")) != str(expected):
                return False
        return True

    def _matches_from(self, msg: NormalizedMessage, from_cfg: dict) -> bool:
        """Return True if *msg* matches the ``from`` block of a forward rule."""
        if msg.instance_id not in from_cfg:
            return False
        for key, expected in from_cfg[msg.instance_id].items():
            if str(msg.channel.get(key, "")) != str(expected):
                return False
        return True

    def _build_formatted(self, msg: NormalizedMessage, msg_cfg: dict) -> tuple[str, dict]:
        """Return (formatted_text, extra_kwargs) for a given msg config block."""
        fmt = msg_cfg.get("msg_format", "{msg}")
        ctx = {
            "platform":    msg.platform,
            "from":        msg.instance_id,
            "username":    msg.user,
            "user_id":     msg.user_id,
            "user_avatar": msg.user_avatar,
            "msg":         msg.text,
        }
        try:
            formatted = fmt.format(**ctx)
        except KeyError as e:
            l.warning(f"msg_format missing key {e}; using raw text")
            formatted = msg.text

        extra: dict = {}
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

    async def _dispatch(self, msg: NormalizedMessage, rule: dict):
        formatted, extra = self._build_formatted(msg, rule.get("msg", {}))

        for target_id, target_channel in rule.get("to", {}).items():
            # Skip echo back to the exact same channel
            if target_id == msg.instance_id and target_channel == msg.channel:
                continue

            if self._is_sensitive(formatted):
                l.warning(
                    f"Message to '{target_id}' blocked: text contains a sensitive "
                    f"value from config (token/secret/webhook). Possible credential leak."
                )
                continue

            sender = self._senders.get(target_id)
            if sender is None:
                l.warning(f"No sender registered for instance '{target_id}'")
                continue

            try:
                await sender(target_channel, formatted, attachments=msg.attachments, **extra)
            except Exception as e:
                l.error(f"Failed to send to '{target_id}': {e}")

    async def _dispatch_connect(self, msg: NormalizedMessage, rule: dict):
        """Fan-out to every channel in the connect rule except the source."""
        global_msg_cfg = rule.get("msg", {})

        for target_id, target_cfg in rule.get("channels", {}).items():
            # Strip the reserved "msg" key to get the bare channel address dict
            target_channel = {k: v for k, v in target_cfg.items() if k != "msg"}

            # Skip echo back to the exact same channel
            if target_id == msg.instance_id and target_channel == msg.channel:
                continue

            # Per-target msg overrides the global msg (target wins on conflict)
            merged_msg_cfg = {**global_msg_cfg, **target_cfg.get("msg", {})}
            formatted, extra = self._build_formatted(msg, merged_msg_cfg)

            if self._is_sensitive(formatted):
                l.warning(
                    f"Message to '{target_id}' blocked: text contains a sensitive "
                    f"value from config (token/secret/webhook). Possible credential leak."
                )
                continue

            sender = self._senders.get(target_id)
            if sender is None:
                l.warning(f"No sender registered for instance '{target_id}'")
                continue

            try:
                await sender(target_channel, formatted, attachments=msg.attachments, **extra)
            except Exception as e:
                l.error(f"Failed to send to '{target_id}': {e}")


# Shared singleton used by all drivers
bridge = Bridge()
