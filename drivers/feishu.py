# Feishu / Lark driver via lark-oapi.
#
# Receive: Feishu pushes events to an HTTP endpoint you expose.
#          This driver starts an aiohttp server on a configurable port.
#          Set that URL in the Feishu developer console under
#          "Event Subscriptions" → "Request URL".
#
# Send: uses the Feishu IM v1 create-message API.
#
# Config keys (under feishu.<instance_id>):
#   app_id             – Feishu app ID  (required)
#   app_secret         – Feishu app secret  (required)
#   verification_token – Event verification token  (from dev console)
#   encrypt_key        – Event encryption key  (leave "" to disable)
#   listen_port        – HTTP port to listen on  (default: 8080)
#   listen_path        – HTTP path for events    (default: "/event")
#
# Rule channel keys:
#   chat_id – Feishu open chat ID, e.g. "oc_xxxxxxxxxxxxxxxxxx"

import asyncio
import json

from aiohttp import web
import lark_oapi as lark
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

import services.logger as log
from services.message import Attachment, NormalizedMessage
from drivers import BaseDriver

l = log.get_logger()


class FeishuDriver(BaseDriver):

    def __init__(self, instance_id: str, config: dict, bridge):
        super().__init__(instance_id, config, bridge)
        self._client: lark.Client | None = None
        self._handler = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self.bridge.register_sender(self.instance_id, self.send)
        self._loop = asyncio.get_running_loop()

        app_id = self.config["app_id"]
        app_secret = self.config["app_secret"]
        verification_token = self.config.get("verification_token", "")
        encrypt_key = self.config.get("encrypt_key", "")
        port = int(self.config.get("listen_port", 8080))
        path = self.config.get("listen_path", "/event")

        # Client for outgoing API calls
        self._client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .build()
        )

        # Event dispatcher for incoming webhook events
        self._handler = (
            lark.EventDispatcherHandler.builder(verification_token, encrypt_key)
            .register_p2_im_message_receive_v1(self._on_message_event)
            .build()
        )

        web_app = web.Application()
        web_app.router.add_post(path, self._handle_http)

        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        l.info(
            f"Feishu [{self.instance_id}] HTTP server listening on "
            f"0.0.0.0:{port}{path}"
        )

        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()

    # ------------------------------------------------------------------
    # Receive — HTTP layer
    # ------------------------------------------------------------------

    async def _handle_http(self, request: web.Request) -> web.Response:
        body = await request.read()
        raw_req = lark.RawRequest(
            uri=request.path,
            headers=dict(request.headers),
            body=body,
        )
        # lark-oapi's do() is synchronous; run in thread pool to avoid blocking
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None, lambda: self._handler.do(raw_req)
        )
        return web.Response(
            body=resp.body,
            status=resp.status_code,
            content_type=resp.content_type or "application/json",
        )

    # ------------------------------------------------------------------
    # Receive — event layer (called from executor thread by lark-oapi)
    # ------------------------------------------------------------------

    def _on_message_event(self, data) -> None:
        """Synchronous callback invoked by lark-oapi inside the executor thread."""
        try:
            event = data.event
            msg = event.message
            sender = event.sender

            if msg.message_type != "text":
                return

            text = json.loads(msg.content).get("text", "").strip()
            if not text:
                return

            chat_id = msg.chat_id
            open_id = (
                sender.sender_id.open_id
                if sender and sender.sender_id
                else ""
            )

            normalized = NormalizedMessage(
                platform="feishu",
                instance_id=self.instance_id,
                channel={"chat_id": chat_id},
                user=open_id,   # Display name requires a separate user-info call
                user_id=open_id,
                user_avatar="",
                text=text,
            )

            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self.bridge.on_message(normalized), self._loop
                )
        except Exception as e:
            l.error(f"Feishu [{self.instance_id}] event parse error: {e}")

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def send(self, channel: dict, text: str, attachments: list[Attachment] | None = None, **kwargs):
        chat_id = channel.get("chat_id")
        if not chat_id:
            l.warning(f"Feishu [{self.instance_id}] send: no chat_id in channel {channel}")
            return
        if self._client is None:
            l.warning(f"Feishu [{self.instance_id}] send: driver not started")
            return

        rich_header = kwargs.get("rich_header")
        if rich_header:
            t, c = rich_header.get("title", ""), rich_header.get("content", "")
            prefix = f"[{t}" + (f" · {c}" if c else "") + "]"
            text = f"{prefix}\n{text}" if text else prefix

        for att in (attachments or []):
            if att.url:
                text += f"\n[{att.type.capitalize()}: {att.name or att.url}]({att.url})"
            elif att.name:
                text += f"\n[{att.type.capitalize()}: {att.name}]"

        req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(json.dumps({"text": text}))
                .build()
            )
            .build()
        )

        loop = asyncio.get_running_loop()
        try:
            resp = await loop.run_in_executor(
                None, lambda: self._client.im.v1.message.create(req)
            )
            if not resp.success():
                l.error(
                    f"Feishu [{self.instance_id}] send failed: "
                    f"code={resp.code} msg={resp.msg}"
                )
        except Exception as e:
            l.error(f"Feishu [{self.instance_id}] send error: {e}")
