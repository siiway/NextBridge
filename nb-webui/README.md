# nb-webui

NextBridge 的 WebUI 管理平面前端 —— 用于在浏览器中管理全局配置、各平台实例与桥接规则。

- 技术栈:**Vite + React + TypeScript + Tailwind CSS v4 + shadcn/ui (Base UI)**
- 界面语言:简体中文
- 后端 API 由 NextBridge 内置提供(挂载于共享 HTTP 服务器的 `/nb-webui` 路径)

## 快速开始

### 环境要求

- [Bun](https://bun.sh) >= 1.2(或任意 Node.js 包管理器)

### 安装依赖

```bash
bun install
```

### 开发调试

```bash
bun run dev
```

开发服务器会把 `/nb-webui/api` 代理到 `http://127.0.0.1:9080`,请先在 NextBridge 目录启动
`uv run main.py` 后再打开前端页面。

### 构建

```bash
bun run build
```

产物输出到 `dist/` 目录。

## 导入到 NextBridge

NextBridge 在启动时会自动挂载本仓库构建出的静态文件:

1. 构建本仓库得到 `dist/` 目录
2. 把 `dist/` 中的**所有文件**复制到 NextBridge 仓库根目录的 `dist/` 目录
3. 重启 NextBridge,访问 `http://<host>:<port>/nb-webui`

```bash
# 在本仓库目录执行
bun run build
# PowerShell (nb-webui 与 NextBridge 同级放置时)
Copy-Item -Recurse -Force dist\* ..\NextBridge\dist\
```

> [!NOTE]
> NextBridge 仓库的 `dist/` 已加入 `.gitignore`,构建产物请自行导入、不要提交。

## 登录

- 默认账号:`admin` / `admin`
- **首次登录必须修改默认密码**,否则无法使用任何管理功能
- 登录凭证保存在 NextBridge 数据目录下的 `webui.json`(与 `config.json` 分离)

## 功能

- **概览**:版本信息、各平台实例数量统计
- **全局设置**:基于后端 JSON Schema 动态渲染的全局配置表单
- **平台实例**:各平台实例的增删改,表单由各驱动器的 Pydantic 模型 Schema 自动生成
- **桥接规则**:connect / forward 规则的向导式表单 + 原始 JSON 编辑器
- **认证**:登录、强制改密、会话 token(24h)、登录限速

## 平台图标

`src/assets/platforms/` 中的平台图标来源于:

- 官方站点 favicon(飞书、钉钉、KOOK、云湖、VoceChat)
- [Simple Icons](https://simpleicons.org)(QQ、Discord、Telegram、Matrix、Signal、Slack、Teams、Google Chat、Mattermost、Rocket.Chat、WhatsApp)
- [icons.siiway.org](https://icons.siiway.org/nextbridge/icon.svg)(NextBridge logo)

图标仅作标识用途,商标与版权归各自所有者所有。

## License

GPL-3.0
