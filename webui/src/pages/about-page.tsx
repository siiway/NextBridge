import { ExternalLinkIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

import nextbridgeLogo from "@/assets/platforms/nextbridge.svg"

export function AboutPage() {
  return (
    <div className="flex max-w-2xl flex-col gap-4">
      <Card>
        <CardHeader className="flex-row items-center gap-4">
          <img
            src={nextbridgeLogo}
            alt="NextBridge"
            className="size-12 rounded-xl"
          />
          <div className="flex flex-col gap-1">
            <CardTitle>NextBridge WebUI 管理平面</CardTitle>
            <CardDescription>
              The chat bridge that links up all the major chat platforms!
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm">
          <p>
            本面板用于管理 NextBridge 的全局配置、各平台实例与桥接规则。
            所有修改直接写入 data/ 目录下的配置文件,大部分改动需要重启
            NextBridge 后生效。
          </p>
          <div className="flex flex-wrap gap-2 pt-2">
            <Button
              variant="outline"
              size="sm"
              render={
                <a
                  href="https://nextbridge.siiway.org/zh"
                  target="_blank"
                  rel="noreferrer"
                />
              }
            >
              使用文档
              <ExternalLinkIcon className="size-3" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              render={
                <a
                  href="https://github.com/siiway/webui"
                  target="_blank"
                  rel="noreferrer"
                />
              }
            >
              webui 源码
              <ExternalLinkIcon className="size-3" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              render={
                <a
                  href="https://github.com/siiway/NextBridge"
                  target="_blank"
                  rel="noreferrer"
                />
              }
            >
              NextBridge
              <ExternalLinkIcon className="size-3" />
            </Button>
          </div>
        </CardContent>
      </Card>
      <p className="text-xs text-muted-foreground">
        平台图标来自各平台官方网站与 Simple Icons,仅作标识用途,版权归各自所有者所有。
      </p>
    </div>
  )
}
