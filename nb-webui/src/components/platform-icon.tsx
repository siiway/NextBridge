import qq from "@/assets/platforms/qq.svg"
import discord from "@/assets/platforms/discord.svg"
import telegram from "@/assets/platforms/telegram.svg"
import feishu from "@/assets/platforms/feishu.ico"
import dingtalk from "@/assets/platforms/dingtalk.ico"
import yunhu from "@/assets/platforms/yunhu.ico"
import kook from "@/assets/platforms/kook.ico"
import matrix from "@/assets/platforms/matrix.svg"
import signalIcon from "@/assets/platforms/signal.svg"
import slack from "@/assets/platforms/slack.svg"
import teams from "@/assets/platforms/teams.svg"
import googlechat from "@/assets/platforms/googlechat.svg"
import mattermost from "@/assets/platforms/mattermost.svg"
import vocechat from "@/assets/platforms/vocechat.ico"
import rocketchat from "@/assets/platforms/rocketchat.svg"
import whatsapp from "@/assets/platforms/whatsapp.svg"
import nextbridge from "@/assets/platforms/nextbridge.svg"
import { WebhookIcon } from "lucide-react"

import { cn } from "@/lib/utils"

export const PLATFORM_ICONS: Record<string, string> = {
  qq,
  discord,
  telegram,
  feishu,
  lark: feishu,
  dingtalk,
  yunhu,
  kook,
  matrix,
  signal: signalIcon,
  slack,
  teams,
  googlechat,
  mattermost,
  vocechat,
  rocketchat,
  whatsapp,
  nextbridge,
}

export const PLATFORM_NAMES: Record<string, string> = {
  qq: "QQ",
  discord: "Discord",
  telegram: "Telegram",
  feishu: "飞书 / Lark",
  dingtalk: "钉钉",
  yunhu: "云湖",
  kook: "KOOK",
  matrix: "Matrix",
  signal: "Signal",
  slack: "Slack",
  teams: "Microsoft Teams",
  googlechat: "Google Chat",
  mattermost: "Mattermost",
  vocechat: "VoceChat",
  rocketchat: "Rocket.Chat",
  whatsapp: "WhatsApp",
  webhook: "Webhook",
}

export function platformName(key: string): string {
  return PLATFORM_NAMES[key] ?? key
}

export function PlatformIcon({
  platform,
  className,
}: {
  platform: string
  className?: string
}) {
  if (platform === "webhook") {
    return <WebhookIcon className={cn("size-5", className)} />
  }
  const src = PLATFORM_ICONS[platform]
  if (src) {
    return (
      <img
        src={src}
        alt={platformName(platform)}
        className={cn("size-5 rounded-sm object-contain", className)}
      />
    )
  }
  return (
    <span
      className={cn(
        "flex size-5 items-center justify-center rounded-sm bg-muted text-xs font-medium text-muted-foreground",
        className,
      )}
    >
      {platform.charAt(0).toUpperCase()}
    </span>
  )
}
