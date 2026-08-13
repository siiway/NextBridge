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

from drivers.registry import register
from typing import Literal

import aiohttp
from aiohttp_socks import ProxyConnector
from pydantic import Field

from services.message import Attachment
from services.config_schema import _DriverConfig
from services.config import get_proxy, UNSET
from services.message_format import apply_rich_header
from drivers import BaseDriver


class WebhookConfig(_DriverConfig):
    url: str
    """Webhook 目标 URL."""
    method: Literal["POST", "PUT", "PATCH"] = "POST"
    """HTTP 请求方法: POST / PUT / PATCH."""
    headers: dict[str, str] = Field(default_factory=dict)
    """自定义 HTTP 请求头."""
    proxy: str | None = UNSET


class WebhookDriver(BaseDriver[WebhookConfig]):
    def __init__(self, instance_id: str, config: WebhookConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._session: aiohttp.ClientSession | None = None
        self._proxy = get_proxy(config.proxy)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        if self._proxy:
            connector = ProxyConnector.from_url(self._proxy, rdns=True)
            self.logger.debug(f"using proxy {self._proxy}")
        else:
            connector = aiohttp.TCPConnector(ssl=True)

        self._session = aiohttp.ClientSession(connector=connector)
        self.bridge.register_sender(self.instance_id, self.send)
        self.logger.info(f"send-only, targeting {self.config.url}")

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
            self.logger.warning("session not ready, message dropped")
            return

        rich_header = kwargs.get("rich_header")
        if rich_header:
            text = apply_rich_header(text, rich_header, style="plain")

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

        # Merge any extra msg config keys, excluding bridge-internal keys
        payload.update({k: v for k, v in kwargs.items() if k != "rich_header"})

        headers = {"Content-Type": "application/json", **self.config.headers}

        try:
            async with self._session.request(
                self.config.method, self.config.url, json=payload, headers=headers
            ) as resp:
                if resp.status not in (200, 201, 202, 204):
                    body = await resp.text()
                    self.logger.error(f"send failed HTTP {resp.status}: {body[:200]}")
        except Exception as e:
            self.logger.error(f"send failed: {e}")


register(
    "webhook", WebhookConfig, WebhookDriver, display_name="Webhook", icon="webhook"
)
