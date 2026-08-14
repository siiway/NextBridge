import { useEffect, useState } from "react"
import { SaveIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { toast } from "@/components/ui/toast"

import { SchemaForm, normalizeValue } from "@/components/schema-form"
import { ValidationErrors } from "@/components/validation-errors"

import { ApiError, apiFetch, apiPut } from "@/lib/api"
import type { ConfigDoc, SchemasResponse } from "@/lib/types"

export function GlobalSettingsPage() {
  const [schemas, setSchemas] = useState<SchemasResponse | null>(null)
  const [config, setConfig] = useState<ConfigDoc | null>(null)
  const [globalValue, setGlobalValue] = useState<Record<string, unknown>>({})
  const [errors, setErrors] = useState<
    Record<string, { path: string; message: string; type: string }[]>
  >({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [schemasResp, configResp] = await Promise.all([
          apiFetch<SchemasResponse>("/schemas"),
          apiFetch<ConfigDoc>("/config"),
        ])
        if (!cancelled) {
          setSchemas(schemasResp)
          setConfig(configResp)
          setGlobalValue(
            normalizeValue(schemasResp.global, configResp["global"] ?? {}) as Record<
              string,
              unknown
            >,
          )
        }
      } catch (err) {
        if (!cancelled) {
          toast.add({
            type: "error",
            title: "加载失败",
            description: err instanceof Error ? err.message : "未知错误",
          })
        }
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  if (!schemas || !config) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-96" />
      </div>
    )
  }

  async function onSave() {
    setSaving(true)
    setErrors({})
    try {
      const next: ConfigDoc = { ...config, global: globalValue }
      await apiPut("/config", next)
      setConfig(next)
      toast.add({
        type: "success",
        title: "配置已保存",
        description: "部分改动需要重启 NextBridge 后生效",
      })
    } catch (err) {
      if (err instanceof ApiError && err.errors) {
        setErrors(err.errors)
        toast.add({ type: "error", title: "配置校验失败", description: err.message })
      } else {
        toast.add({
          type: "error",
          title: "保存失败",
          description: err instanceof Error ? err.message : "未知错误",
        })
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex max-w-2xl flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>全局设置</CardTitle>
          <CardDescription>
            全局配置对所有平台生效,保存后部分改动需要重启 NextBridge 才生效
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ValidationErrors errors={errors} prefix="global" />
          <SchemaForm
            schema={schemas.global}
            value={globalValue}
            onChange={setGlobalValue}
          />
        </CardContent>
      </Card>
      <div className="flex justify-end">
        <Button onClick={onSave} disabled={saving}>
          <SaveIcon />
          {saving ? "保存中…" : "保存配置"}
        </Button>
      </div>
    </div>
  )
}
