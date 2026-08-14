import { useEffect, useMemo, useState } from "react"
import { EditIcon, PlusIcon, RouteIcon, TrashIcon } from "lucide-react"

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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { toast } from "@/components/ui/toast"

import { PlatformIcon, platformName } from "@/components/platform-icon"

import { apiFetch, apiPut } from "@/lib/api"
import type { InstancesResponse, Rule, RulesDoc, SchemasResponse } from "@/lib/types"

type RuleDialogState = { mode: "create" } | { mode: "edit"; index: number } | null

type ChannelFieldMeta = { key: string; label: string; description?: string }

const CONNECT_TEMPLATE: Rule = {
  type: "connect",
  channels: {},
  msg: { msg_format: "{user} @ {from}: {msg}" },
}

export function RulesPage() {
  const [rules, setRules] = useState<Rule[] | null>(null)
  const [instances, setInstances] = useState<Record<string, string>>({})
  const [schemas, setSchemas] = useState<SchemasResponse | null>(null)
  const [dialog, setDialog] = useState<RuleDialogState>(null)
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [rulesResp, instancesResp, schemasResp] = await Promise.all([
          apiFetch<RulesDoc>("/rules"),
          apiFetch<InstancesResponse>("/instances"),
          apiFetch<SchemasResponse>("/schemas"),
        ])
        if (!cancelled) {
          setRules(rulesResp.rules ?? [])
          setInstances(instancesResp.instances ?? {})
          setSchemas(schemasResp)
        }
      } catch (err) {
        if (!cancelled) {
          toast.add({
            type: "error",
            title: "加载规则失败",
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

  const configuredRules = useMemo(() => rules ?? [], [rules])

  async function persist(next: Rule[]): Promise<boolean> {
    try {
      const resp = await apiPut<{ ok: boolean; count: number }>("/rules", {
        rules: next,
      })
      setRules(next)
      toast.add({
        type: "success",
        title: "规则已保存",
        description: `共 ${resp.count} 条规则`,
      })
      return true
    } catch (err) {
      toast.add({
        type: "error",
        title: "保存规则失败",
        description: err instanceof Error ? err.message : "未知错误",
      })
      return false
    }
  }

  async function onSaveRule(rule: Rule, index: number | null) {
    setSaving(true)
    const next = [...configuredRules]
    if (index === null) {
      next.push(rule)
    } else {
      next[index] = rule
    }
    const ok = await persist(next)
    setSaving(false)
    if (ok) {
      setDialog(null)
    }
  }

  async function onDeleteRule(index: number) {
    setSaving(true)
    const next = [...configuredRules]
    next.splice(index, 1)
    const ok = await persist(next)
    setSaving(false)
    if (ok) {
      setDeleteTarget(null)
    }
  }

  if (rules === null) {
    return <p className="text-sm text-muted-foreground">加载中…</p>
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div className="flex flex-col gap-1">
            <CardTitle>桥接规则</CardTitle>
            <CardDescription>
              connect 规则将列出的频道双向连通;forward 规则定义单向转发
            </CardDescription>
          </div>
          <Button size="sm" onClick={() => setDialog({ mode: "create" })}>
            <PlusIcon />
            新建规则
          </Button>
        </CardHeader>
        <CardContent>
          {configuredRules.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-10 text-center">
              <RouteIcon className="size-8 text-muted-foreground/50" />
              <p className="text-sm text-muted-foreground">
                还没有任何规则,点击「新建规则」开始桥接
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {configuredRules.map((rule, index) => (
                <div
                  key={rule.id ?? index}
                  className="flex items-center gap-3 rounded-lg border p-3"
                >
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="font-mono">
                        {String(rule.type ?? "?")}
                      </Badge>
                      <span className="truncate font-mono text-xs text-muted-foreground">
                        {rule.id ?? "(自动生成 ID)"}
                      </span>
                    </div>
                    <span className="truncate text-sm">
                      {summarizeRule(rule)}
                    </span>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`编辑规则 ${index + 1}`}
                    onClick={() => setDialog({ mode: "edit", index })}
                  >
                    <EditIcon />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="text-destructive hover:text-destructive"
                    aria-label={`删除规则 ${index + 1}`}
                    onClick={() => setDeleteTarget(index)}
                  >
                    <TrashIcon />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {dialog && (
        <RuleDialog
          key={`${dialog.mode}-${dialog.mode === "edit" ? dialog.index : "new"}`}
          mode={dialog.mode}
          initialRule={
            dialog.mode === "edit" ? configuredRules[dialog.index] : undefined
          }
          saving={saving}
          instances={instances}
          channelFieldsByPlatform={schemas?.meta ? Object.fromEntries(
            Object.entries(schemas.meta).map(([k, v]) => [k, v.channel_fields ?? []])
          ) : {}}
          onClose={() => setDialog(null)}
          onSave={(rule) =>
            onSaveRule(rule, dialog.mode === "edit" ? dialog.index : null)
          }
        />
      )}

      {deleteTarget !== null && (
        <AlertDialog open onOpenChange={(open) => !open && setDeleteTarget(null)}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>确认删除规则?</AlertDialogTitle>
              <AlertDialogDescription>
                将删除第 {deleteTarget + 1} 条规则(类型:
                {String(configuredRules[deleteTarget]?.type ?? "?")}),此操作无法撤销。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>取消</AlertDialogCancel>
              <AlertDialogAction
                variant="destructive"
                onClick={() => onDeleteRule(deleteTarget)}
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

function RuleDialog({
  mode,
  initialRule,
  saving,
  instances,
  channelFieldsByPlatform,
  onClose,
  onSave,
}: {
  mode: "create" | "edit"
  initialRule?: Rule
  saving: boolean
  instances: Record<string, string>
  channelFieldsByPlatform: Record<string, ChannelFieldMeta[]>
  onClose: () => void
  onSave: (rule: Rule) => void
}) {
  const [rule, setRule] = useState<Rule>(() =>
    initialRule ? structuredClone(initialRule) : structuredClone(CONNECT_TEMPLATE),
  )
  const [jsonText, setJsonText] = useState(() =>
    JSON.stringify(initialRule ?? CONNECT_TEMPLATE, null, 2),
  )
  const [jsonInvalid, setJsonInvalid] = useState(false)
  const [activeTab, setActiveTab] = useState("form")
  const [error, setError] = useState<string | null>(null)

  function setRuleType(type: string) {
    setRule((prev) => {
      const next = structuredClone(prev)
      next.type = type
      if (type === "connect") {
        delete next["from"]
        delete next["to"]
        if (!next.channels) {
          next.channels = {}
        }
      } else {
        delete next.channels
        if (!next.from) {
          next.from = {}
        }
        if (!next.to) {
          next.to = {}
        }
      }
      return next
    })
  }

  function syncJson() {
    setJsonText(JSON.stringify(rule, null, 2))
    setJsonInvalid(false)
  }

  function submit() {
    let finalRule: Rule
    if (activeTab === "json") {
      try {
        finalRule = JSON.parse(jsonText) as Rule
      } catch {
        setError("JSON 格式不合法,请修正后再保存")
        setJsonInvalid(true)
        setActiveTab("json")
        return
      }
    } else {
      finalRule = structuredClone(rule)
    }
    if (!finalRule || typeof finalRule !== "object" || Array.isArray(finalRule)) {
      setError("规则必须是对象")
      return
    }
    const type = String(finalRule.type ?? "")
    if (type !== "connect" && type !== "forward") {
      setError("规则类型必须是 connect 或 forward")
      return
    }
    const channelTargets =
      type === "connect" ? finalRule.channels : finalRule.to
    if (
      !channelTargets ||
      typeof channelTargets !== "object" ||
      Object.keys(channelTargets).length === 0
    ) {
      setError(type === "connect" ? "请至少添加一个频道" : "to 目标不能为空")
      return
    }
    setError(null)
    onSave(finalRule)
  }

  const isConnect = String(rule.type) !== "forward"

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {mode === "create" ? "新建规则" : "编辑规则"}
          </DialogTitle>
          <DialogDescription>
            使用表单快速创建常用规则,或在「原始 JSON」页签直接编辑完整规则对象
          </DialogDescription>
        </DialogHeader>
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList>
            <TabsTrigger
              value="form"
              onClick={() => {
                syncJson()
              }}
            >
              表单
            </TabsTrigger>
            <TabsTrigger
              value="json"
              onClick={() => {
                syncJson()
              }}
            >
              原始 JSON
            </TabsTrigger>
          </TabsList>
          <TabsContent value="form" className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label>规则类型</Label>
              <Select
                value={String(rule.type ?? "connect")}
                onValueChange={(v) => v && setRuleType(v)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="connect">connect(双向连通)</SelectItem>
                  <SelectItem value="forward">forward(单向转发)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="rule-id">规则 ID(可选)</Label>
              <Input
                id="rule-id"
                placeholder="留空自动生成稳定 ID"
                value={String(rule.id ?? "")}
                onChange={(e) =>
                  setRule((prev) => ({
                    ...prev,
                    id: e.target.value || undefined,
                  }))
                }
              />
            </div>
            {isConnect ? (
              <ChannelFieldsEditor
                label="channels（双向连通的频道）"
                value={(rule.channels as Record<string, Record<string, string>>) ?? {}}
                onChange={(v) =>
                  setRule((prev) => ({ ...prev, channels: v }))
                }
                single={false}
                instances={instances}
                channelFieldsByPlatform={channelFieldsByPlatform}
              />
            ) : (
              <>
                <ChannelFieldsEditor
                  label="from（消息来源）"
                  value={(rule.from as Record<string, Record<string, string>>) ?? {}}
                  onChange={(v) => setRule((prev) => ({ ...prev, from: v }))}
                  single
                  instances={instances}
                  channelFieldsByPlatform={channelFieldsByPlatform}
                />
                <ChannelFieldsEditor
                  label="to（转发目标）"
                  value={(rule.to as Record<string, Record<string, string>>) ?? {}}
                  onChange={(v) => setRule((prev) => ({ ...prev, to: v }))}
                  single={false}
                  instances={instances}
                  channelFieldsByPlatform={channelFieldsByPlatform}
                />
              </>
            )}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="msg-format">msg_format(消息格式,可选)</Label>
              <Input
                id="msg-format"
                placeholder='{user} @ {from}: {msg}'
                value={String(
                  (rule.msg as Record<string, unknown> | undefined)
                    ?.msg_format ?? "",
                )}
                onChange={(e) =>
                  setRule((prev) => {
                    const msg: Record<string, unknown> = {
                      ...((prev.msg as Record<string, unknown>) ?? {}),
                    }
                    if (e.target.value) {
                      msg.msg_format = e.target.value
                    } else {
                      delete msg.msg_format
                    }
                    return { ...prev, msg }
                  })
                }
              />
            </div>
          </TabsContent>
          <TabsContent value="json">
            <Textarea
              rows={18}
              className={`font-mono text-xs ${jsonInvalid ? "border-destructive" : ""}`}
              value={jsonText}
              onChange={(e) => {
                setJsonText(e.target.value)
                try {
                  const parsed = JSON.parse(e.target.value) as Rule
                  setRule(parsed)
                  setJsonInvalid(false)
                } catch {
                  setJsonInvalid(true)
                }
              }}
            />
          </TabsContent>
        </Tabs>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <DialogFooter className="-mx-4 -mb-4">
          <Button variant="outline" onClick={onClose} disabled={saving}>
            取消
          </Button>
          <Button onClick={submit} disabled={saving}>
            {saving ? "保存中…" : "保存规则"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ChannelFieldsEditor({
  label,
  value,
  onChange,
  single,
  instances,
  channelFieldsByPlatform,
}: {
  label: string
  value: Record<string, Record<string, string>>
  onChange: (value: Record<string, Record<string, string>>) => void
  single: boolean
  instances: Record<string, string>
  channelFieldsByPlatform: Record<string, ChannelFieldMeta[]>
}) {
  const instanceIds = Object.keys(value)
  const rows = single ? instanceIds.slice(0, 1) : instanceIds
  const instanceOptions = Object.keys(instances)

  function setInstance(oldId: string, newId: string) {
    const next = { ...value }
    delete next[oldId]
    if (newId) {
      next[newId] = value[oldId] ?? {}
    }
    onChange(next)
  }

  function addRow() {
    // Prefer the first available instance that isn't already used
    const unused = instanceOptions.find((id) => !(id in value))
    onChange({ ...value, [unused ?? `实例${Object.keys(value).length + 1}`]: {} })
  }

  function removeRow(instanceId: string) {
    const next = { ...value }
    delete next[instanceId]
    onChange(next)
  }

  return (
    <div className="flex flex-col gap-2">
      <Label>{label}</Label>
      {rows.length === 0 && (
        <p className="text-sm text-muted-foreground">暂无频道，点击下方按钮添加</p>
      )}
      {rows.map((instanceId) => {
        const platform = instances[instanceId]
        const declared = platform ? (channelFieldsByPlatform[platform] ?? []) : []
        return (
          <div key={instanceId} className="rounded-lg border p-3">
            <div className="mb-2 flex items-center gap-2">
              <Select
                value={instanceId}
                onValueChange={(v) => v && setInstance(instanceId, v)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="选择实例" />
                </SelectTrigger>
                <SelectContent>
                  {instanceOptions.map((id) => (
                    <SelectItem key={id} value={id}>
                      <span className="flex items-center gap-2">
                        <PlatformIcon
                          platform={instances[id] ?? ""}
                          className="size-4"
                        />
                        {platformName(instances[id] ?? "")} · {id}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {!single && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label="删除该频道"
                  onClick={() => removeRow(instanceId)}
                >
                  <TrashIcon />
                </Button>
              )}
            </div>
            {platform ? (
              <ChannelFields
                declared={declared}
                fields={value[instanceId] ?? {}}
                onChange={(fields) => {
                  const next = { ...value }
                  next[instanceId] = fields
                  onChange(next)
                }}
              />
            ) : (
              <p className="text-sm text-muted-foreground">
                请选择一个已配置的实例
              </p>
            )}
          </div>
        )
      })}
      {!single && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="w-fit"
          onClick={addRow}
        >
          <PlusIcon />
          添加频道
        </Button>
      )}
    </div>
  )
}

function ChannelFields({
  declared,
  fields,
  onChange,
}: {
  declared: ChannelFieldMeta[]
  fields: Record<string, string>
  onChange: (fields: Record<string, string>) => void
}) {
  const customKeys = Object.keys(fields).filter(
    (k) => !declared.some((d) => d.key === k),
  )

  function setField(key: string, val: string) {
    const next = { ...fields }
    if (val) {
      next[key] = val
    } else {
      delete next[key]
    }
    onChange(next)
  }

  function setCustomKey(oldKey: string, newKey: string) {
    if (oldKey === newKey) {
      return
    }
    const next = { ...fields }
    const val = next[oldKey] ?? ""
    delete next[oldKey]
    if (newKey.trim()) {
      next[newKey.trim()] = val
    }
    onChange(next)
  }

  return (
    <div className="flex flex-col gap-2">
      {declared.map((field) => (
        <div key={field.key} className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="w-32 shrink-0 font-mono text-xs text-muted-foreground">
              {field.label}
            </span>
            <Input
              className="flex-1 font-mono text-xs"
              value={fields[field.key] ?? ""}
              placeholder={field.label}
              onChange={(e) => setField(field.key, e.target.value)}
            />
          </div>
          {field.description && (
            <p className="text-xs text-muted-foreground">{field.description}</p>
          )}
        </div>
      ))}
      {customKeys.map((key, idx) => (
        <div key={`custom-${idx}`} className="flex items-center gap-2">
          <Input
            className="w-36 font-mono text-xs"
            placeholder="字段名"
            value={key}
            onChange={(e) => setCustomKey(key, e.target.value)}
          />
          <Input
            className="flex-1 font-mono text-xs"
            placeholder="值"
            value={fields[key] ?? ""}
            onChange={(e) => setField(key, e.target.value)}
          />
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label="删除该字段"
            onClick={() => setField(key, "")}
          >
            <TrashIcon />
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="w-fit"
        onClick={() => onChange({ ...fields, [""]: "" })}
      >
        <PlusIcon />
        添加自定义字段
      </Button>
    </div>
  )
}

function summarizeRule(rule: Rule): string {
  const type = String(rule.type ?? "?")
  if (type === "connect") {
    const channels = rule.channels as Record<string, unknown> | undefined
    const count = channels ? Object.keys(channels).length : 0
    return `连通 ${count} 个频道`
  }
  const from = rule.from as Record<string, unknown> | undefined
  const to = rule.to as Record<string, unknown> | undefined
  return `从 ${Object.keys(from ?? {}).join(", ") || "?"} 转发到 ${
    Object.keys(to ?? {}).length
  } 个目标`
}
