# DingTalk driver via alibabacloud-dingtalk.
#
# Receive: DingTalk pushes events to an HTTP endpoint you expose (outgoing
#          robot webhook).  This driver starts an aiohttp server on a
#          configurable port.  Set the URL in the DingTalk developer console
#          under your bot's "Message Receive Mode" → "HTTP Mode".
#
# Send: uses the DingTalk Robot v1.0 org_group_send API, authenticated via
#       an OAuth 2.0 access token that is cached and auto-refreshed.
#
# Config keys (under dingtalk.<instance_id>):
#   app_key        – DingTalk app key   (required)
#   app_secret     – DingTalk app secret (required)
#   robot_code     – Bot robot code     (required for sending)
#   signing_secret – Webhook signing secret (optional; skips verify if absent)
#   listen_port    – HTTP port          (default: 8082)
#   listen_path    – HTTP path          (default: "/dingtalk/event")
#
# Rule channel keys:
#   open_conversation_id – DingTalk open conversation ID
#                          (from the "openConversationId" field in incoming
#                           webhook events, or from the DingTalk developer
#                           console for the group)

import asyncio
import base64
import hashlib
import hmac
import json
import time

from aiohttp import web
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models
from alibabacloud_dingtalk.oauth2_1_0.client import Client as OAuthClient
from alibabacloud_dingtalk.oauth2_1_0 import models as oauth_models
from alibabacloud_dingtalk.robot_1_0.client import Client as RobotClient
from alibabacloud_dingtalk.robot_1_0 import models as robot_models

import services.logger as log
from services.message import Attachment, NormalizedMessage
from services.config_schema import _DriverConfig
from drivers import BaseDriver


class DingTalkConfig(_DriverConfig):
    app_key:        str
    app_secret:     str
    robot_code:     str
    signing_secret: str = ""
    listen_port:    int = 8082
    listen_path:    str = "/dingtalk/event"

l = log.get_logger()

_DINGTALK_ENDPOINT = "api.dingtalk.com"


class DingTalkDriver(BaseDriver[DingTalkConfig]):

    def __init__(self, instance_id: str, config: DingTalkConfig, bridge):
        super().__init__(instance_id, config, bridge)
        self._oauth_client: OAuthClient | None = None
        self._robot_client: RobotClient | None = None
        self._access_token: str = ""
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self.bridge.register_sender(self.instance_id, self.send)

        cfg = open_api_models.Config(endpoint=_DINGTALK_ENDPOINT)
        self._oauth_client = OAuthClient(cfg)
        self._robot_client = RobotClient(cfg)

        port = self.config.listen_port
        path = self.config.listen_path

        web_app = web.Application()
        web_app.router.add_post(path, self._handle_http)

        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        l.info(
            f"DingTalk [{self.instance_id}] HTTP server listening on "
            f"0.0.0.0:{port}{path}"
        )

        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def _handle_http(self, request: web.Request) -> web.Response:
        try:
            body: dict = await request.json()
        except Exception:
            return web.json_response({"message": "bad request"}, status=400)

        if self.config.signing_secret:
            ts = request.headers.get("timestamp", "")
            sig = request.headers.get("sign", "")
            if not _verify_sign(ts, self.config.signing_secret, sig):
                l.warning(f"DingTalk [{self.instance_id}] webhook signature mismatch")
                return web.json_response({"message": "forbidden"}, status=403)

        if body.get("msgtype") != "text":
            return web.json_response({})

        text = body.get("text", {}).get("content", "").strip()
        if not text:
            return web.json_response({})

        # "openConversationId" is the API-usable ID; fall back to "conversationId"
        open_conv_id = body.get("openConversationId") or body.get("conversationId", "")
        sender_nick = body.get("senderNick", "")
        sender_id = body.get("senderId", "")

        msg = NormalizedMessage(
            platform="dingtalk",
            instance_id=self.instance_id,
            channel={"open_conversation_id": open_conv_id},
            user=sender_nick or sender_id,
            user_id=sender_id,
            user_avatar="",
            text=text,
        )
        await self.bridge.on_message(msg)
        return web.json_response({})

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def send(self, channel: dict, text: str, attachments: list[Attachment] | None = None, **kwargs):
        open_conv_id = channel.get("open_conversation_id")
        if not open_conv_id:
            l.warning(
                f"DingTalk [{self.instance_id}] send: "
                f"no open_conversation_id in channel {channel}"
            )
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

        robot_code = self.config.robot_code

        try:
            token = await self._get_access_token()
        except Exception as e:
            l.error(f"DingTalk [{self.instance_id}] access token error: {e}")
            return

        headers = robot_models.OrgGroupSendHeaders(
            x_acs_dingtalk_access_token=token
        )
        req = robot_models.OrgGroupSendRequest(
            robot_code=robot_code,
            open_conversation_id=open_conv_id,
            msg_key="sampleText",
            msg_param=json.dumps({"title": "NextBridge", "content": text}),
        )

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: self._robot_client.org_group_send_with_options(
                    req, headers, util_models.RuntimeOptions()
                ),
            )
        except Exception as e:
            l.error(f"DingTalk [{self.instance_id}] send failed: {e}")

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    async def _get_access_token(self) -> str:
        if time.monotonic() < self._token_expires_at - 60:
            return self._access_token

        req = oauth_models.GetAccessTokenRequest(
            app_key=self.config.app_key,
            app_secret=self.config.app_secret,
        )
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None, lambda: self._oauth_client.get_access_token(req)
        )
        self._access_token = resp.body.access_token
        self._token_expires_at = time.monotonic() + (resp.body.expire_in or 7200)
        l.debug(f"DingTalk [{self.instance_id}] access token refreshed")
        return self._access_token


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _verify_sign(timestamp: str, secret: str, sign: str) -> bool:
    """Verify DingTalk webhook HMAC-SHA256 signature."""
    if not timestamp or not sign:
        return False
    try:
        string_to_sign = f"{timestamp}\n{secret}"
        expected = base64.b64encode(
            hmac.new(
                secret.encode("utf-8"),
                string_to_sign.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        return hmac.compare_digest(expected, sign)
    except Exception:
        return False


from drivers.registry import register
register("dingtalk", DingTalkConfig, DingTalkDriver)
