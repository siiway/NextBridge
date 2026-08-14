export class ApiError extends Error {
  status: number
  errors?: Record<string, { path: string; message: string; type: string }[]>

  constructor(
    status: number,
    message: string,
    errors?: Record<string, { path: string; message: string; type: string }[]>,
  ) {
    super(message)
    this.status = status
    this.errors = errors
  }
}

const BASE = "/nb-webui/api"

export function getToken(): string | null {
  return sessionStorage.getItem("nb-webui-token")
}

export function setToken(token: string | null) {
  if (token) {
    sessionStorage.setItem("nb-webui-token", token)
  } else {
    sessionStorage.removeItem("nb-webui-token")
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  }
  const token = getToken()
  if (token) {
    headers["Authorization"] = `Bearer ${token}`
  }
  const resp = await fetch(`${BASE}${path}`, { ...options, headers })
  let data: unknown = null
  try {
    data = await resp.json()
  } catch {
    // non-JSON body
  }
  if (!resp.ok) {
    const detail =
      data &&
      typeof data === "object" &&
      "detail" in data &&
      typeof (data as { detail: unknown }).detail === "string"
        ? ((data as { detail: string }).detail)
        : `请求失败 (${resp.status})`
    const errors =
      data && typeof data === "object" && "errors" in data
        ? ((data as { errors: unknown }).errors as ApiError["errors"])
        : undefined
    throw new ApiError(resp.status, detail, errors)
  }
  return data as T
}

export function apiPut<T = unknown>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: "PUT",
    body: JSON.stringify(body),
  })
}
