import { useEffect, useMemo, useState } from "react"
import { EditIcon, PlusIcon, TrashIcon } from "lucide-react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { toast } from "@/components/ui/toast"

import { PlatformIcon, platformName } from "@/components/platform-icon"
import { SchemaForm, normalizeValue } from "@/components/schema-form"

import { ApiError, apiFetch, apiPut } from "@/lib/api"
import type {
  ConfigDoc,
  JsonSchema,
  PlatformInstances,
  SchemasResponse,
} from "@/lib/types"

type InstanceDialogState =
  | { mode: "create" }
  | { mode: "edit"; instanceId: string }
  | null

export function PlatformsPage({
  initialPlatform,
}: {
  initialPlatform: string | null
}) {
  const [schemas, setSchemas] = useState<SchemasResponse | null>(null)
  const [config, setConfig] = useState<ConfigDoc | null>(null)
  const [selected, setSelected] = useState<string | null>(initialPlatform)
  const [dialog, setDialog] = useState<InstanceDialogState>(null)
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
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

  useEffect(() => {
    if (initialPlatform) {
      setSelected(initialPlatform)
    }
  }, [initialPlatform])

  const platforms = useMemo(
    () => (schemas ? Object.keys(schemas.drivers) : []),
    [schemas],
  )

  useEffect(() => {
    if (!selected && platforms.length > 0) {
      setSelected(platforms[0])
    }
  }, [platforms, selected])

  if (!schemas || !config) {
    return (
      <div className="flex gap-4">
        <Skeleton className="h-64 w-52" />
        <Skeleton className="h-64 flex-1" />
      </div>
    )
  }

  const instances = (config[selected ?? ""] ?? {}) as PlatformInstances

  async function persist(next: ConfigDoc): Promise<boolean> {
    try {
      await apiPut("/config", next)
      setConfig(next)
      return true
    } catch (err) {
      if (err instanceof ApiError && err.errors) {
        toast.add({
          type: "error",
          title: "配置校验失败",
          description: err.message,
        })
      } else {
        toast.add({
          type: "error",
          title: "保存失败",
          description: err instanceof Error ? err.message : "未知错误",
        })
      }
      return false
    }
  }

  async function onSaveInstance(instanceId: string, value: Record<string, unknown>) {
    if (!selected) {
      return
    }
    setSaving(true)
    const next: ConfigDoc = {
      ...config,
      [selected]: { ...instances, [instanceId]: value },
    }
    const ok = await persist(next)
    setSaving(false)
    if (ok) {
      setDialog(null)
      toast.add({
        type: "success",
        title: "实例已保存",
        description: `${selected} / ${instanceId}`,
      })
    }
  }

  async function onDeleteInstance(instanceId: string) {
    if (!selected) {
      return
    }
    setSaving(true)
    const nextInstances: PlatformInstances = { ...instances }
    delete nextInstances[instanceId]
    const next: ConfigDoc = { ...config, [selected]: nextInstances }
    const ok = await persist(next)
    setSaving(false)
    if (ok) {
      setDeleteTarget(null)
      toast.add({
        type: "success",
        title: "实例已删除",
        description: `${selected} / ${instanceId}`,
      })
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        {platforms.map((platform) => {
          const count = Object.keys((config[platform] ?? {}) as object).length
          return (
            <Button
              key={platform}
              variant={selected === platform ? "default" : "outline"}
              size="sm"
              onClick={() => setSelected(platform)}
            >
              <PlatformIcon platform={platform} />
              {platformName(platform)}
              <Badge variant="secondary" className="h-5 px-1.5 text-xs">
                {count}
              </Badge>
            </Button>
          )
        })}
      </div>

      {selected && (
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div className="flex flex-col gap-1">
              <CardTitle>{platformName(selected)} 实例</CardTitle>
              <CardDescription>
                {schemas.meta[selected]?.description ||
                  `管理 ${selected} 平台的实例配置`}
              </CardDescription>
            </div>
            <Button size="sm" onClick={() => setDialog({ mode: "create" })}>
              <PlusIcon />
              添加实例
            </Button>
          </CardHeader>
          <CardContent>
            {Object.keys(instances).length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                该平台还没有配置任何实例,点击「添加实例」开始
              </p>
            ) : (
              <div className="flex flex-col gap-2">
                {Object.entries(instances).map(([instanceId, raw]) => (
                  <div
                    key={instanceId}
                    className="flex items-center gap-3 rounded-lg border p-3"
                  >
                    <div className="flex min-w-0 flex-1 flex-col gap-1">
                      <span className="truncate font-medium">{instanceId}</span>
                      <span className="truncate font-mono text-xs text-muted-foreground">
                        {summarize(raw)}
                      </span>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`编辑实例 ${instanceId}`}
                      onClick={() =>
                        setDialog({ mode: "edit", instanceId })
                      }
                    >
                      <EditIcon />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="text-destructive hover:text-destructive"
                      aria-label={`删除实例 ${instanceId}`}
                      onClick={() => setDeleteTarget(instanceId)}
                    >
                      <TrashIcon />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {selected && dialog && (
        <InstanceDialog
          key={`${dialog.mode}-${dialog.mode === "edit" ? dialog.instanceId : "new"}`}
          schema={schemas.drivers[selected]}
          platform={selected}
          mode={dialog.mode}
          existingId={dialog.mode === "edit" ? dialog.instanceId : ""}
          initialValue={
            dialog.mode === "edit"
              ? (instances[dialog.instanceId] as Record<string, unknown>)
              : undefined
          }
          saving={saving}
          onClose={() => setDialog(null)}
          onSave={onSaveInstance}
        />
      )}

      {selected && deleteTarget && (
        <AlertDialog open onOpenChange={(open) => !open && setDeleteTarget(null)}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>确认删除实例?</AlertDialogTitle>
              <AlertDialogDescription>
                将删除 {selected} 平台下的实例「{deleteTarget}
                」,此操作无法撤销。请同时检查并清理桥接规则中对它的引用。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>取消</AlertDialogCancel>
              <AlertDialogAction
                variant="destructive"
                onClick={() => onDeleteInstance(deleteTarget)}
                disabled={saving}
              >
                删除
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </div>
  )
}

function InstanceDialog({
  schema,
  platform,
  mode,
  existingId,
  initialValue,
  saving,
  onClose,
  onSave,
}: {
  schema: JsonSchema
  platform: string
  mode: "create" | "edit"
  existingId: string
  initialValue?: Record<string, unknown>
  saving: boolean
  onClose: () => void
  onSave: (instanceId: string, value: Record<string, unknown>) => void
}) {
  const [instanceId, setInstanceId] = useState(
    mode === "create" ? "" : existingId,
  )
  const [value, setValue] = useState<Record<string, unknown>>(() =>
    normalizeValue(schema, initialValue ?? {}) as Record<string, unknown>,
  )
  const [idError, setIdError] = useState<string | null>(null)

  function submit() {
    const id = instanceId.trim()
    if (!id) {
      setIdError("实例 ID 不能为空")
      return
    }
    if (!/^[\w.-]+$/.test(id)) {
      setIdError("实例 ID 只能包含字母、数字、下划线、点与连字符")
      return
    }
    setIdError(null)
    onSave(id, value)
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {mode === "create" ? "添加实例" : `编辑实例「${existingId}」`}
          </DialogTitle>
          <DialogDescription>
            {platformName(platform)} ({platform}) — 带默认值的字段留空即可
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="instance-id">实例 ID</Label>
            <Input
              id="instance-id"
              value={instanceId}
              onChange={(e) => setInstanceId(e.target.value)}
              placeholder="例如: 我的QQ"
              disabled={mode === "edit"}
            />
            {idError && <p className="text-sm text-destructive">{idError}</p>}
          </div>
          <SchemaForm schema={schema} value={value} onChange={setValue} />
        </div>
        <DialogFooter className="-mx-4 -mb-4">
          <Button variant="outline" onClick={onClose} disabled={saving}>
            取消
          </Button>
          <Button onClick={submit} disabled={saving}>
            {saving ? "保存中…" : "保存"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function summarize(raw: Record<string, unknown>): string {
  const entries = Object.entries(raw)
    .slice(0, 3)
    .map(([key, val]) => {
      const text =
        typeof val === "string"
          ? val
          : JSON.stringify(val) ?? String(val)
      return `${key}=${text.length > 32 ? `${text.slice(0, 32)}…` : text}`
    })
  const extra = entries.length < Object.keys(raw).length ? " …" : ""
  return entries.join(" · ") + extra
}
