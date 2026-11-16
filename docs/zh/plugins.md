> 本文档由 AI 编写，已经人工审核。

# 插件开发

NextBridge 支持通用插件系统，可扩展驱动集成之外的功能。插件可以订阅事件、注册自定义命令、添加数据库迁移，并访问完整的桥接 API。

## 插件架构

插件是继承 `BasePlugin` 的 Python 类，带有 `PluginMeta` 描述符。在导入时通过 `plugins.registry.register()` 注册。

### 插件生命周期

| 阶段 | 方法 | 说明 |
|---|---|---|
| 注册 | `register("name", PluginClass)` | 在模块导入时调用 |
| 加载 | `async on_load(ctx)` | 接收 `PluginContext`，进行初始设置 |
| 启用 | `async on_enable()` | 订阅事件、注册命令 |
| 禁用 | `async on_disable()` | 仅做额外清理——可追踪的注册会被自动移除 |
| 卸载 | `async on_unload()` | 移除前的最终清理 |
| 重启 | `PluginManager.restart_plugin(name)` | 一步完成 `disable → unload → load → enable` |

### 插件状态

`CREATED` → `LOADED` → `ENABLED` → `DISABLED` → `UNLOADED`

## 创建插件

### 步骤 1：定义插件类

```python
from plugins import BasePlugin, PluginMeta
from plugins.registry import register


class MyPlugin(BasePlugin):
    meta = PluginMeta(
        name="my_plugin",
        version="1.0.0",
        display_name="我的插件",
        description="做一些有用的事情",
        author="You",
        dependencies=[],
    )

    async def on_load(self, ctx):
        self._ctx = ctx

    async def on_enable(self):
        pass

    async def on_disable(self):
        pass

    async def on_unload(self):
        pass


register("my_plugin", MyPlugin)
```

### 步骤 2：配置插件

```yaml
global:
  plugins:
    general:
      enabled:
        - my_plugin
    config:
      my_plugin:
        key: value
```

## PluginContext

`PluginContext` 对象提供核心服务的访问：

| 属性 | 类型 | 说明 |
|---|---|---|
| `ctx.bridge` | `Bridge` | 核心路由引擎——注册命令、检查发送者 |
| `ctx.event_bus` | `EventBus` | 订阅生命周期和消息事件 |
| `ctx.middleware` | `MiddlewareChain` | 注册接收/发送中间件 |
| `ctx.http_server` | `HttpServerManager` | 挂载 HTTP 子应用（如果 HTTP 服务器正在运行） |
| `ctx.config` | `dict` | 来自 `plugins.config.<name>` 的插件配置 |
| `ctx.version` | `str` | NextBridge 版本字符串 |
| `ctx.config_path` | `Path` | 配置文件路径 |
| `ctx.data_path` | `str` | 运行时数据目录 |
| `ctx.db()` | `MessageDB` | 消息/用户映射的数据库访问 |
| `ctx.media()` | `module` | 媒体工具（下载附件、转换格式） |
| `ctx.logger(name)` | `Logger` | 获取 loguru 日志记录器 |

### 可追踪注册助手

推荐使用以下助手，而非直接调用 `ctx.bridge` / `ctx.event_bus` / `ctx.middleware`。通过它们完成的注册会被插件管理器记录，并在插件被禁用或卸载时自动移除，无需手动清理。

| 助手 | 说明 |
|---|---|
| `ctx.register_command(name, handler)` | 注册 `/<前缀> <name>` 命令 |
| `ctx.on_event(event, handler)` | 订阅 `EventBus` 事件 |
| `ctx.add_receive_middleware(name, handler, priority=100)` | 添加接收中间件 |
| `ctx.add_send_middleware(name, handler, priority=100)` | 添加发送中间件 |
| `ctx.cleanup()` | 手动移除所有已记录的注册 |

## 注册命令

插件可以注册自定义命令，用户通过 `/<prefix> <command>` 调用：

```python
class MyPlugin(BasePlugin):
    async def on_enable(self):
        self._ctx.register_command("hello", self._handle_hello)

    async def _handle_hello(self, msg, args):
        sender_info = self._ctx.bridge._senders.get(msg.instance_id)
        if sender_info:
            _, sender = sender_info
            await sender(msg.channel, "来自 MyPlugin 的问候！")
```

处理函数接收 `(msg: NormalizedMessage, args: list[str])`。

## 订阅事件

使用 `ctx.on_event` 响应系统事件；该订阅会在禁用/卸载时自动移除：

```python
class MyPlugin(BasePlugin):
    async def on_enable(self):
        self._ctx.on_event("bridge.message", self._on_message)

    async def _on_message(self, instance_id, platform, channel, text, **kwargs):
        # 每条桥接消息都会调用
        pass
```

### 标准事件

| 事件 | 参数 |
|---|---|
| `bridge.message` | `instance_id`, `platform`, `channel`, `user`, `user_id`, `text`, `message_id`, `time`, `attachments` |
| `driver.starting` | `instance_id` |
| `driver.started` | `instance_id` |
| `driver.crashed` | `instance_id`, `error` |
| `driver.stopped` | `instance_id` |
| `health_changed` | `driver`, `old`, `new` |
| `plugin.loaded` | `name` |
| `plugin.enabled` | `name` |
| `plugin.disabled` | `name` |
| `plugin.error` | `name`, `error` |

## 依赖

插件可以通过 `PluginMeta.dependencies` 声明它依赖的其他插件。当某个依赖处于已加载或已启用状态时，禁用/卸载它会被拒绝（抛出 `PluginDependencyError`）；请先卸载依赖它的插件。启动关闭流程不检查依赖，会强制卸载全部插件。

## 自定义数据库迁移

插件可以注册自己的数据库迁移步骤：

```python
from pathlib import Path
from services.db_migrations import register_plugin_migration

MIGRATION_FILE = Path(__file__).parent / "migrations" / "0-1.py"
register_plugin_migration(from_version=0, to_version=1, file_path=MIGRATION_FILE)
```

迁移文件必须导出 `upgrade(conn, dialect_name)` 函数，与内置迁移使用相同的契约。

## 插件发现

插件从四个来源发现（按优先级顺序，后者覆盖前者）：

| 来源 | 位置 |
|---|---|
| 内置 | 项目目录下的 `plugins/*.py` |
| 入口点 | 声明 `nextbridge.plugins` 入口点组的 pip 包 |
| 外部 | `plugins.general.external` 中声明的 pip 包 |
| 本地路径 | `plugins.paths` 中列出的目录 |

## 配置参考

| 键 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `plugins.general.enabled` | `list[str]` | `[]` | 要启用的插件名称 |
| `plugins.general.external` | `dict` | `{}` | 外部插件模块，按名称键值 |
| `plugins.paths` | `list[str]` | `[]` | 扫描插件 `.py` 文件的本地目录 |
| `plugins.config` | `dict[str, dict]` | `{}` | 按插件名称键值的配置 |

### 外部插件配置

```yaml
plugins:
  general:
    external:
      my_plugin:
        module: "nextbridge_myplugin"
```

## 驱动器插件

驱动器与通用插件分开分发。若 pip 安装的驱动器声明了 `nextbridge.drivers`
入口点组，将被自动发现：

```toml
[project.entry-points."nextbridge.drivers"]
myplatform = "nextbridge_myplatform.driver"
```

该模块必须在导入时调用 `drivers.registry.register()`（以及可选的
`drivers.registry.register_cli()`）。也可以在
`global.plugins.drivers.external` 中显式声明，或将 `.py` 文件放入
`global.plugins.paths` 列出的目录——完整的优先级表与示例见
[配置 → 外部驱动器](./configuration#外部驱动器)。

## 内置插件

### stats

统计跨平台桥接消息并通过 `/<prefix> stats` 命令报告。

**配置：**

```yaml
plugins:
  config:
    stats:
      interval: 300
```

## 管理 API

可以通过管理 API 检查和控制插件（所有响应都使用统一的 `{"ok": ..., "data": ...}` 信封）：

```
GET  /_nextbridge/plugins
POST /_nextbridge/admin/plugins/{name}/enable
POST /_nextbridge/admin/plugins/{name}/disable
POST /_nextbridge/admin/plugins/{name}/restart
```

`GET` 返回：

```json
{
  "ok": true,
  "data": {
    "plugins": {
      "stats": {
        "state": "ENABLED",
        "version": "1.0.0",
        "error": null,
        "source": "builtin"
      }
    }
  }
}
```

需要 HTTP Basic Auth（`plugins.admin.user` / `plugins.admin.password`）。完整参考见[管理 API](./admin-api)。