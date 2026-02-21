from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Reusable bool coercion: "true" / "1" / "yes" → True
# ---------------------------------------------------------------------------

def _coerce_bool(v: object) -> object:
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes")
    return v


CoercedBool = Annotated[bool, BeforeValidator(_coerce_bool)]


# ---------------------------------------------------------------------------
# Base for all driver config blocks — unknown keys are a validation error
# ---------------------------------------------------------------------------

class _DriverConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Per-driver config models
# ---------------------------------------------------------------------------

class NapCatConfig(_DriverConfig):
    ws_url:           str                         = "ws://127.0.0.1:3001"
    ws_token:         str                         = ""
    max_file_size:    int                         = 10 * 1024 * 1024
    file_send_mode:   Literal["stream", "base64"] = "stream"
    cqface_mode:      Literal["gif", "emoji"]     = "gif"
    stream_threshold: int                         = 0


class DiscordConfig(_DriverConfig):
    send_method:                         Literal["webhook", "bot"] = "webhook"
    webhook_url:                         str                       = ""
    bot_token:                           str                       = ""
    max_file_size:                       int                       = 8 * 1024 * 1024
    send_as_bot_when_using_cqface_emoji: CoercedBool               = False


class TelegramConfig(_DriverConfig):
    bot_token:        str
    max_file_size:    int = 50 * 1024 * 1024
    rich_header_host: str = ""


class FeishuConfig(_DriverConfig):
    app_id:             str
    app_secret:         str
    verification_token: str = ""
    encrypt_key:        str = ""
    listen_port:        int = 8080
    listen_path:        str = "/event"


class DingTalkConfig(_DriverConfig):
    app_key:        str
    app_secret:     str
    robot_code:     str
    signing_secret: str = ""
    listen_port:    int = 8082
    listen_path:    str = "/dingtalk/event"


class YunhuConfig(_DriverConfig):
    token:        str = ""
    webhook_port: int = 8765
    webhook_path: str = "/yunhu-webhook"
    proxy_host:   str = ""


class KookConfig(_DriverConfig):
    token:         str
    max_file_size: int = 25 * 1024 * 1024


class MatrixConfig(_DriverConfig):
    homeserver:    str
    user_id:       str
    password:      str = ""
    access_token:  str = ""
    max_file_size: int = 10 * 1024 * 1024

    @model_validator(mode="after")
    def _require_auth(self) -> MatrixConfig:
        if not self.password and not self.access_token:
            raise ValueError("requires 'password' or 'access_token'")
        return self


class SignalConfig(_DriverConfig):
    api_url:       str
    number:        str
    max_file_size: int = 50 * 1024 * 1024


class SlackConfig(_DriverConfig):
    bot_token:            str                       = ""
    app_token:            str                       = ""
    send_method:          Literal["bot", "webhook"] = "bot"
    incoming_webhook_url: str                       = ""
    signing_secret:       str                       = ""
    listen_port:          int                       = 0
    listen_path:          str                       = "/slack/events"
    max_file_size:        int                       = 50 * 1024 * 1024


class WebhookConfig(_DriverConfig):
    url:     str
    method:  Literal["POST", "PUT", "PATCH"] = "POST"
    headers: dict[str, str]                  = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Top-level application config
# ---------------------------------------------------------------------------

class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    napcat:   dict[str, NapCatConfig]   = {}
    discord:  dict[str, DiscordConfig]  = {}
    telegram: dict[str, TelegramConfig] = {}
    feishu:   dict[str, FeishuConfig]   = {}
    dingtalk: dict[str, DingTalkConfig] = {}
    yunhu:    dict[str, YunhuConfig]    = {}
    kook:     dict[str, KookConfig]     = {}
    matrix:   dict[str, MatrixConfig]   = {}
    signal:   dict[str, SignalConfig]   = {}
    slack:    dict[str, SlackConfig]    = {}
    webhook:  dict[str, WebhookConfig]  = {}
