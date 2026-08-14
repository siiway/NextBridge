import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { PlusIcon, TrashIcon } from "lucide-react"

import type { JsonSchema } from "@/lib/types"
import { cn } from "@/lib/utils"

const SENSITIVE_RE = /token|secret|password|webhook|key/i

function resolve(schema: JsonSchema): JsonSchema {
  if (schema.$ref) {
    const def = schema.$ref.replace(/^#\/\$defs\//, "")
    const target = schema.$defs?.[def]
    if (target) {
      return resolve({ ...target, $defs: schema.$defs })
    }
  }
  return schema
}

function effectiveType(schema: JsonSchema): string | undefined {
  const s = resolve(schema)
  if (s.type) {
    return Array.isArray(s.type) ? s.type[0] : s.type
  }
  if (s.anyOf) {
    for (const candidate of s.anyOf) {
      const resolved = resolve(candidate)
      if (resolved.type && resolved.type !== "null") {
        return Array.isArray(resolved.type) ? resolved.type[0] : resolved.type
      }
    }
  }
  if (s.properties || s.additionalProperties) {
    return "object"
  }
  return undefined
}

export function normalizeValue(schema: JsonSchema, value: unknown): unknown {
  const s = resolve(schema)
  if (s.default !== undefined && (value === undefined || value === null)) {
    return structuredClone(s.default)
  }
  const t = effectiveType(s)
  if (t === "object") {
    const obj: Record<string, unknown> = {}
    const current =
      value && typeof value === "object" && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : {}
    for (const [key, prop] of Object.entries(s.properties ?? {})) {
      obj[key] = normalizeValue(prop, current[key])
    }
    return obj
  }
  if (t === "array") {
    if (Array.isArray(value)) {
      return value
    }
    if (Array.isArray(s.default)) {
      return structuredClone(s.default)
    }
    return []
  }
  if (value === undefined || value === null) {
    if (t === "boolean") {
      return false
    }
    return ""
  }
  return value
}

interface SchemaFormProps {
  schema: JsonSchema
  value: Record<string, unknown>
  onChange: (value: Record<string, unknown>) => void
  className?: string
}

export function SchemaForm({ schema, value, onChange, className }: SchemaFormProps) {
  const s = resolve(schema)
  const props = s.properties ?? {}
  const entries = Object.entries(props)
  return (
    <div className={cn("flex flex-col gap-5", className)}>
      {entries.map(([key, prop]) => (
        <SchemaField
          key={key}
          name={key}
          schema={prop}
          value={value[key]}
          onChange={(v) => onChange({ ...value, [key]: v })}
        />
      ))}
    </div>
  )
}

interface SchemaFieldProps {
  name: string
  schema: JsonSchema
  value: unknown
  onChange: (value: unknown) => void
}

function SchemaField({ name, schema, value, onChange }: SchemaFieldProps) {
  const s = resolve(schema)
  const type = effectiveType(s)
  const label = s.title || name
  const description = s.description
  const sensitive = SENSITIVE_RE.test(name)

  let control: React.ReactNode = null

  if (type === "object") {
    const current =
      value && typeof value === "object" && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : {}
    control = (
      <div className="rounded-lg border p-4">
        {description && (
          <p className="mb-3 text-sm text-muted-foreground">{description}</p>
        )}
        <SchemaForm
          schema={s}
          value={current}
          onChange={(v) => onChange(v)}
        />
      </div>
    )
    return <fieldset className="flex flex-col gap-2">{control}</fieldset>
  }

  if (type === "boolean") {
    control = (
      <div className="flex items-center gap-2">
        <Switch
          checked={Boolean(value)}
          onCheckedChange={(checked) => onChange(checked)}
        />
        <span className="text-sm text-muted-foreground">
          {Boolean(value) ? "已开启" : "已关闭"}
        </span>
      </div>
    )
  } else if (s.enum) {
    const options = s.enum
      .filter((item): item is string | number => item !== null)
      .map(String)
    const current = value === undefined || value === null ? "" : String(value)
    control = (
      <Select
        value={current || undefined}
        onValueChange={(v) => onChange(v === "" ? undefined : v)}
      >
        <SelectTrigger className="w-full">
          <SelectValue placeholder="留空使用默认值" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="">留空使用默认值</SelectItem>
          {options.map((option) => (
            <SelectItem key={option} value={option}>
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    )
  } else if (type === "array") {
    const items = s.items ? resolve(s.items) : undefined
    if (items && items.type === "object") {
      control = (
        <JsonTextarea
          value={value}
          onChange={onChange}
          placeholder='[{"key": "value"}]'
        />
      )
    } else {
      const list = Array.isArray(value)
        ? (value as unknown[])
        : []
      control = (
        <div className="flex flex-col gap-2">
          {list.map((item, index) => (
            <div key={index} className="flex items-center gap-2">
              <Input
                value={item === null || item === undefined ? "" : String(item)}
                onChange={(e) => {
                  const next = [...list]
                  next[index] = e.target.value
                  onChange(next)
                }}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label="删除该项"
                onClick={() => {
                  const next = [...list]
                  next.splice(index, 1)
                  onChange(next)
                }}
              >
                <TrashIcon />
              </Button>
            </div>
          ))}
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-fit"
            onClick={() => onChange([...list, ""])}
          >
            <PlusIcon />
            添加一项
          </Button>
        </div>
      )
    }
  } else if (type === "number" || type === "integer") {
    control = (
      <Input
        type="number"
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(e) => {
          const raw = e.target.value
          if (raw === "") {
            onChange(undefined)
          } else {
            const parsed = Number(raw)
            if (!Number.isNaN(parsed)) {
              onChange(type === "integer" ? Math.trunc(parsed) : parsed)
            }
          }
        }}
      />
    )
  } else if (type === "string") {
    control = (
      <Input
        type={sensitive ? "password" : "text"}
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(e) => onChange(e.target.value)}
      />
    )
  } else {
    control = (
      <JsonTextarea
        value={value}
        onChange={onChange}
        placeholder="输入合法 JSON"
      />
    )
  }

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={`sf-${name}`}>{label}</Label>
      <div>{control}</div>
      {description && (
        <p className="text-sm text-muted-foreground">{description}</p>
      )}
    </div>
  )
}

function JsonTextarea({
  value,
  onChange,
  placeholder,
}: {
  value: unknown
  onChange: (value: unknown) => void
  placeholder?: string
}) {
  const [text, setText] = useState(() =>
    value === undefined ? "" : JSON.stringify(value, null, 2),
  )
  const [invalid, setInvalid] = useState(false)
  useEffect(() => {
    const next = value === undefined ? "" : JSON.stringify(value, null, 2)
    setText((prev) => {
      if (prev === next) {
        return prev
      }
      try {
        const parsedPrev = prev.trim() === "" ? undefined : JSON.parse(prev)
        if (JSON.stringify(parsedPrev) === JSON.stringify(value)) {
          return prev
        }
      } catch {
        // keep last edit
      }
      return next
    })
  }, [value])
  return (
    <Textarea
      rows={5}
      className={cn("font-mono text-xs", invalid && "border-destructive")}
      placeholder={placeholder}
      value={text}
      onChange={(e) => {
        setText(e.target.value)
        const raw = e.target.value.trim()
        if (raw === "") {
          setInvalid(false)
          onChange(undefined)
          return
        }
        try {
          onChange(JSON.parse(raw))
          setInvalid(false)
        } catch {
          setInvalid(true)
        }
      }}
    />
  )
}
