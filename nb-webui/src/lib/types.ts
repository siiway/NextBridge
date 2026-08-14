export interface JsonSchema {
  title?: string
  description?: string
  type?: string | string[]
  anyOf?: JsonSchema[]
  oneOf?: JsonSchema[]
  $ref?: string
  $defs?: Record<string, JsonSchema>
  default?: unknown
  enum?: unknown[]
  properties?: Record<string, JsonSchema>
  required?: string[]
  items?: JsonSchema
  additionalProperties?: JsonSchema | boolean
}

export interface SchemasResponse {
  global: JsonSchema
  drivers: Record<string, JsonSchema>
  meta: Record<string, { description?: string }>
}

export interface InfoResponse {
  version: string
  config_path: string
  rules_path: string
  platforms: Record<string, number>
}

export interface LoginResponse {
  token: string
  username: string
  must_change_password: boolean
}

export interface AuthStatusResponse {
  username: string
  must_change_password: boolean
}

export interface ValidationErrorItem {
  path: string
  message: string
  type: string
}

export type PlatformInstances = Record<string, Record<string, unknown>>
export type ConfigDoc = Record<string, unknown>

export interface Rule {
  id?: string
  type?: string
  [key: string]: unknown
}

export interface RulesDoc {
  rules: Rule[]
}

export interface PageProps {
  navigate: (page: string) => void
}
