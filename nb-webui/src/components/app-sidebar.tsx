import { useEffect, useState } from "react"
import {
  InfoIcon,
  LayoutDashboardIcon,
  LogOutIcon,
  MoonIcon,
  PlugZapIcon,
  RouteIcon,
  SettingsIcon,
  SunIcon,
} from "lucide-react"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar"

import nextbridgeLogo from "@/assets/platforms/nextbridge.svg"
import { useAuth } from "@/lib/auth"

const NAV_ITEMS = [
  { key: "overview", label: "概览", icon: LayoutDashboardIcon },
  { key: "global", label: "全局设置", icon: SettingsIcon },
  { key: "platforms", label: "平台实例", icon: PlugZapIcon },
  { key: "rules", label: "桥接规则", icon: RouteIcon },
]

export function AppSidebar({
  page,
  navigate,
}: {
  page: string
  navigate: (page: string) => void
}) {
  const { username, logout } = useAuth()
  const [dark, setDark] = useState(
    () => localStorage.getItem("nb-webui-theme") === "dark",
  )

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark)
    localStorage.setItem("nb-webui-theme", dark ? "dark" : "light")
  }, [dark])

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" onClick={() => navigate("overview")}>
              <img
                src={nextbridgeLogo}
                alt="NextBridge"
                className="size-6 rounded-md"
              />
              <span className="font-semibold">NextBridge</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>管理</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV_ITEMS.map((item) => (
                <SidebarMenuItem key={item.key}>
                  <SidebarMenuButton
                    isActive={page === item.key}
                    onClick={() => navigate(item.key)}
                  >
                    <item.icon />
                    <span>{item.label}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel>其他</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  isActive={page === "about"}
                  onClick={() => navigate("about")}
                >
                  <InfoIcon />
                  <span>关于</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={() => setDark((prev) => !prev)}
              title="切换明暗主题"
            >
              {dark ? <SunIcon /> : <MoonIcon />}
              <span>{dark ? "浅色模式" : "深色模式"}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton onClick={logout} title="退出登录">
              <LogOutIcon />
              <span>退出登录 ({username})</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
