import { useEffect, useState } from "react"
import { BookOpenIcon, ExternalLinkIcon, PlugZapIcon, RouteIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

import { PlatformIcon, platformName } from "@/components/platform-icon"

import { apiFetch } from "@/lib/api"
import type { InfoResponse, PageProps, SchemasResponse } from "@/lib/types"

export function OverviewPage({ navigate }: PageProps) {
  const [info, setInfo] = useState<InfoResponse | null>(null)
  const [schemas, setSchemas] = useState<SchemasResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [infoResp, schemasResp] = await Promise.all([
          apiFetch<InfoResponse>("/info"),
          apiFetch<SchemasResponse>("/schemas"),
        ])
        if (!cancelled) {
          setInfo(infoResp)
          setSchemas(schemasResp)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "加载失败")
        }
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  if (error) {
    return <p className="text-destructive">{error}</p>
  }

  if (!info || !schemas) {
    return (
      <div className="flex flex-col gap-4">
        <div className="grid gap-4 sm:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-64" />
      </div>
    )
  }

  const totalInstances = Object.values(info.platforms).reduce(
    (sum, count) => sum + count,
    0,
  )
  const platforms = Object.keys(schemas.drivers)

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader>
            <CardDescription>NextBridge 版本</CardDescription>
            <CardTitle className="font-mono">v{info.version}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>已配置平台</CardDescription>
            <CardTitle>
              {platforms.filter((p) => (info.platforms[p] ?? 0) > 0).length}
              <span className="text-base font-normal text-muted-foreground">
                {" "}
                / {platforms.length}
              </span>
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>实例总数</CardDescription>
            <CardTitle>{totalInstances}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>平台配置状态</CardTitle>
          <CardDescription>
            点击平台卡片可直接管理对应平台的实例
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {platforms.map((platform) => {
              const count = info.platforms[platform] ?? 0
              return (
                <button
                  key={platform}
                  type="button"
                  onClick={() => navigate(`platforms:${platform}`)}
                  className="flex items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent hover:text-accent-foreground"
                >
                  <PlatformIcon platform={platform} className="size-7" />
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate font-medium">
                      {platformName(platform)}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {platform}
                    </span>
                  </div>
                  {count > 0 ? (
                    <Badge variant="secondary">{count} 个实例</Badge>
                  ) : (
                    <Badge variant="outline" className="text-muted-foreground">
                      未配置
                    </Badge>
                  )}
                </button>
              )
            })}
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={() => navigate("platforms")}>
          <PlugZapIcon />
          管理平台实例
        </Button>
        <Button variant="outline" onClick={() => navigate("rules")}>
          <RouteIcon />
          编辑桥接规则
        </Button>
        <Button
          variant="ghost"
          render={
            <a
              href="https://nextbridge.siiway.org/zh"
              target="_blank"
              rel="noreferrer"
            />
          }
        >
          <BookOpenIcon />
          使用文档
          <ExternalLinkIcon className="size-3" />
        </Button>
      </div>

      <p className="text-xs text-muted-foreground">
        配置文件:{info.config_path} · 规则文件:{info.rules_path}
      </p>
    </div>
  )
}
