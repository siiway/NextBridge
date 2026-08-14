import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react"

import { ApiError, apiFetch, getToken, setToken } from "@/lib/api"
import type { AuthStatusResponse, LoginResponse } from "@/lib/types"

interface AuthState {
  ready: boolean
  authenticated: boolean
  username: string | null
  mustChangePassword: boolean
  login: (username: string, password: string) => Promise<void>
  changePassword: (oldPassword: string, newPassword: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false)
  const [authenticated, setAuthenticated] = useState(false)
  const [username, setUsername] = useState<string | null>(null)
  const [mustChangePassword, setMustChangePassword] = useState(false)

  const applyStatus = useCallback((status: AuthStatusResponse) => {
    setUsername(status.username)
    setMustChangePassword(status.must_change_password)
    setAuthenticated(true)
  }, [])

  useEffect(() => {
    let cancelled = false
    async function check() {
      if (!getToken()) {
        setReady(true)
        return
      }
      try {
        const status = await apiFetch<AuthStatusResponse>("/auth/status")
        if (!cancelled) {
          applyStatus(status)
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          setToken(null)
        }
      } finally {
        if (!cancelled) {
          setReady(true)
        }
      }
    }
    void check()
    return () => {
      cancelled = true
    }
  }, [applyStatus])

  const login = useCallback(
    async (loginName: string, password: string) => {
      const resp = await apiFetch<LoginResponse>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: loginName, password }),
      })
      setToken(resp.token)
      setUsername(resp.username)
      setMustChangePassword(resp.must_change_password)
      setAuthenticated(true)
    },
    [],
  )

  const changePassword = useCallback(
    async (oldPassword: string, newPassword: string) => {
      const resp = await apiFetch<LoginResponse>("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          old_password: oldPassword,
          new_password: newPassword,
        }),
      })
      setToken(resp.token)
      setMustChangePassword(false)
    },
    [],
  )

  const logout = useCallback(() => {
    setToken(null)
    setAuthenticated(false)
    setUsername(null)
    setMustChangePassword(false)
  }, [])

  return (
    <AuthContext.Provider
      value={{
        ready,
        authenticated,
        username,
        mustChangePassword,
        login,
        changePassword,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider")
  }
  return ctx
}
