interface ValidationErrorItem {
  path: string
  message: string
  type: string
}

export function ValidationErrors({
  errors,
  prefix,
}: {
  errors: Record<string, ValidationErrorItem[]>
  prefix?: string
}) {
  const entries = Object.entries(errors).filter(
    ([group]) => !prefix || group === prefix,
  )
  const total = entries.reduce((sum, [, items]) => sum + items.length, 0)
  if (total === 0) {
    return null
  }
  return (
    <div className="mb-4 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
      {entries.map(([group, items]) => (
        <div key={group}>
          {items.map((item, index) => (
            <p key={index}>
              <span className="font-medium">{group}</span>
              {item.path ? ` → ${item.path}` : ""}:{item.message}
            </p>
          ))}
        </div>
      ))}
    </div>
  )
}
