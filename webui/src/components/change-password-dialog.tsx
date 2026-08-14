import { useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
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
import { toast } from "@/components/ui/toast"

import { ApiError } from "@/lib/api"
import { useAuth } from "@/lib/auth"

export function ChangePasswordDialog({
  open,
  onOpenChange,
  dismissible,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  dismissible: boolean
}) {
  const { changePassword } = useAuth()
  const [oldPassword, setOldPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (newPassword.length < 8) {
      setError("新密码长度不能少于 8 位")
      return
    }
    if (newPassword !== confirm) {
      setError("两次输入的新密码不一致")
      return
    }
    setLoading(true)
    try {
      await changePassword(oldPassword, newPassword)
      toast.add({ type: "success", title: "密码已修改", description: "现在可以正常使用管理功能了" })
      setOldPassword("")
      setNewPassword("")
      setConfirm("")
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "修改密码失败,请稍后重试")
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={dismissible ? onOpenChange : () => {}}
      disablePointerDismissal={!dismissible}
    >
      <DialogContent showCloseButton={dismissible}>
        <DialogHeader>
          <DialogTitle>修改密码</DialogTitle>
          <DialogDescription>
            {dismissible
              ? "定期修改密码可以提升账号安全性"
              : "首次登录必须修改默认密码 (admin / admin) 后才能使用 WebUI 管理功能"}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="cp-old">原密码</Label>
            <Input
              id="cp-old"
              type="password"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              autoComplete="current-password"
              autoFocus
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="cp-new">新密码</Label>
            <Input
              id="cp-new"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="cp-confirm">确认新密码</Label>
            <Input
              id="cp-confirm"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter className="-mx-0 -mb-0 rounded-b-none border-t-0 bg-transparent p-0 sm:p-0">
            <Button type="submit" disabled={loading}>
              {loading ? "提交中…" : "确认修改"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
