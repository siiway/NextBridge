# Generic outgoing webhook driver (send-only).
#
# When a message is routed to this driver, it POSTs a JSON payload to the
# configured URL.  There is no receive side.
#
# Config keys (under webhook.<instance_id>):
#   url     – HTTP endpoint to send to (required)
#   method  – HTTP method: "POST" (default), "PUT", "PATCH"
#   headers – Dict of extra request headers (e.g. {"Authorization": "Bearer ..."})
#
# Rule channel keys:
#   (none — all messages go to the same url; the channel dict from the rule
#    is passed through as-is in the payload)
#
# Payload sent on each message:
#   {
#     "text":        "<formatted text>",
#     "channel":     { ... rule channel dict ... },
#     "attachments": [{ "type", "url", "name", "size" }, ...],
#     ... any extra msg config keys passed through by the bridge ...
#   }
#
# The "rich_header" kwarg (if present) is applied as a [Title · Content] prefix
# to "text" and is not included as a separate field.

from typing import Literal

import aiohttp
from pydantic import Field

import services.logger as log
from services.message import Attachment
from services.config_schema import _DriverConfig
from drivers import BaseDriver


class WebhookConfig(_DriverConfig):
    url:     str
    method:  Literal["POST", "PUT", "PATCH"] = "POST"
    headers: dict[str, str]                  = Field(default_factory=dict)

l = log.get_logger()


class WebhookDriver(BaseDriver[WebhookConfig]):

    def __init__(self, instance_id: str, config: WebhookConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self._session = aiohttp.ClientSession()
        self.bridge.register_sender(self.instance_id, self.send)
        l.info(f"Webhook [{self.instance_id}] send-only, targeting {self.config.url}")

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def send(
        self,
        channel: dict,
        text: str,
        attachments: list[Attachment] | None = None,
        **kwargs,
    ):
        if self._session is None:
            l.warning(f"Webhook [{self.instance_id}] session not ready, message dropped")
            return

        rich_header = kwargs.pop("rich_header", None)
        if rich_header:
            t, c = rich_header.get("title", ""), rich_header.get("content", "")
            prefix = f"[{t}" + (f" · {c}" if c else "") + "]"
            text = f"{prefix}\n{text}" if text else prefix

        payload: dict = {
            "text": text,
            "channel": channel,
            "attachments": [
                {
                    "type": att.type,
                    "url": att.url,
                    "name": att.name,
                    "size": att.size,
                }
                for att in (attachments or [])
            ],
        }

        # Merge any extra msg config keys (webhook_title, webhook_avatar, custom fields…)
        payload.update(kwargs)

        headers = {"Content-Type": "application/json", **self.config.headers}

        try:
            async with self._session.request(self.config.method, self.config.url, json=payload, headers=headers) as resp:
                if resp.status not in (200, 201, 202, 204):
                    body = await resp.text()
                    l.error(
                        f"Webhook [{self.instance_id}] send failed "
                        f"HTTP {resp.status}: {body[:200]}"
                    )
        except Exception as e:
            l.error(f"Webhook [{self.instance_id}] send failed: {e}")


from drivers.registry import register
register("webhook", WebhookConfig, WebhookDriver)
