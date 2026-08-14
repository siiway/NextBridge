import { useEffect, useState } from "react"

import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import { Toaster } from "@/components/ui/toast"

import { AppSidebar } from "@/components/app-sidebar"
import { ChangePasswordDialog } from "@/components/change-password-dialog"

import { useAuth } from "@/lib/auth"
import { AuthProvider } from "@/lib/auth"
import { AboutPage } from "@/pages/about-page"
import { GlobalSettingsPage } from "@/pages/global-page"
import { LoginPage } from "@/pages/login-page"
import { OverviewPage } from "@/pages/overview-page"
import { PlatformsPage } from "@/pages/platforms-page"
import { RulesPage } from "@/pages/rules-page"

const PAGE_TITLES: Record<string, string> = {
  overview: "概览",
  global: "全局设置",
  platforms: "平台实例",
  rules: "桥接规则",
  about: "关于",
}

function Shell() {
  const { ready, authenticated, mustChangePassword } = useAuth()
  const [page, setPage] = useState("overview")
  const [changeOpen, setChangeOpen] = useState(false)

  useEffect(() => {
    if (authenticated && mustChangePassword) {
      setChangeOpen(true)
    }
  }, [authenticated, mustChangePassword])

  if (!ready) {
    return (
      <div className="flex min-h-svh items-center justify-center bg-muted/30 text-sm text-muted-foreground">
        加载中…
      </div>
    )
  }

  if (!authenticated) {
    return (
      <>
        <LoginPage />
        <Toaster />
      </>
    )
  }

  const navigate = (target: string) => {
    if (target.startsWith("platforms:")) {
      setPage(target)
    } else {
      setPage(target)
    }
  }

  const platformParam = page.startsWith("platforms:")
    ? page.slice("platforms:".length)
    : null
  const basePage = page.startsWith("platforms:") ? "platforms" : page
  const title = PAGE_TITLES[basePage] ?? "NextBridge"

  return (
    <SidebarProvider>
      <AppSidebar page={basePage} navigate={navigate} />
      <SidebarInset>
        <header className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
          <SidebarTrigger />
          <Separator orientation="vertical" className="h-5" />
          <h1 className="text-sm font-medium">{title}</h1>
        </header>
        <main className="flex flex-1 flex-col gap-4 p-4">
          {basePage === "overview" && <OverviewPage navigate={navigate} />}
          {basePage === "global" && <GlobalSettingsPage />}
          {basePage === "platforms" && (
            <PlatformsPage initialPlatform={platformParam} />
          )}
          {basePage === "rules" && <RulesPage />}
          {basePage === "about" && <AboutPage />}
        </main>
      </SidebarInset>
      <ChangePasswordDialog
        open={changeOpen}
        onOpenChange={(open) => setChangeOpen(open)}
        dismissible={!mustChangePassword}
      />
      <Toaster />
    </SidebarProvider>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  )
}
