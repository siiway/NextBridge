# NextBridge 开发

1. 请忽略本文档语言，跟随用户的语言回答
2. 项目使用 `uv` 作为包管理器，依赖须写入 `pyproject.toml` 而非 `requirements.txt` 或 `uv.lock`
3. 项目可用 lint/type check: `ruff check --fix` & `ruff format` & `ty check` (未在虚拟环境可能需要 `uv run ...`)
4. 文档站源码在 `docs/` 下（VitePress），中英文均在同一个仓库：`docs/en/`、`docs/zh/`
5. 在 增/删/改 功能时，同步修改对应的中文 & 英文文档部分（`docs/en/` 与 `docs/zh/`）
6. 在进行功能/行为性更改（非底层或对用户无影响逻辑更改）后，及时更新文档以反映最新状态
7. 在增加新 driver 时，需要在 `README.md` 的 `Special Thanks` 部分增加 driver 使用的库 (没有则不管)
8. 在达到 1.0 版本之前，不需要考虑代码的旧版本兼容性 (但是需要记忆下破坏性修改，以便在 release notes 中提及)
9. driver 的第三方依赖必须在 `__init__` 中延迟导入，模块顶层只放标准库与核心依赖（`fastapi` / `pydantic`）。CLI 启动时会 import 全部 driver 收集 `register_cli()`，顶层导入可选依赖会让缺少该依赖的环境直接报错
10. driver 的第三方依赖若为**可选**（例如 `neonize` 需要系统库 `libmagic`），延迟导入失败时要抛出带可操作提示的 `RuntimeError`，而不是裸 `ImportError`
11. **改动依赖或 PostgreSQL 相关代码后必须额外验证**（现有 `pytest` 只用 SQLite，覆盖不到这些路径）：
    - 跑 `uv lock` 后确认 `uv.lock` 的 sqlalchemy 仍在 `>=2.1,<2.2`
    - 用真实 PostgreSQL 跑一遍启动迁移，确认 8 个 migration 全部通过（见 `RELEASING.md`）
    - 在没有 `libmagic` 的干净容器里 import 所有 driver，确认无一失败（见 `RELEASING.md`）
12. 文档（Markdown）中不要为了控制行宽手动换行：VitePress 会把源文件中的换行渲染为空格，影响观感。一个段落/列表项/表格单元格写成一整行
13. Docker 镜像默认**不会**随 push 自动构建：只有当 push 到 `main`/`dev` 的 commit message 中包含 `<docker-build>`（或打 `v*` tag）时才会触发 Docker Image CI。用户要求"构建/发布镜像"时，默认即指在 commit message 中加上 `<docker-build>` 标记；CI 的 `paths-ignore` 也已排除纯文档/CI 改动

# 可用的 driver api 文档

> [!IMPORTANT]
> 请只根据现在**正在编辑的功能**按需读取

## QQ (NapCat) API Docs

https://s.apifox.cn/apidoc/docs-site/5348325/llms.txt

## QQ (Lagrange.OneBot) API Docs

https://lagrange-onebot.apifox.cn/llms.txt

## QQ (OneBot v11) API Docs

https://github.com/botuniverse/onebot-11#%E5%86%85%E5%AE%B9%E7%9B%AE%E5%BD%95

## Yunhu API Docs

- 接入准备:
  - 开发须知: https://www.yhchat.com/document/1-3
  - 服务端 API 列表: https://www.yhchat.com/document/1-4
  - 服务端错误代码: https://www.yhchat.com/document/1-5
- 消息管理:
  - 发送消息: https://www.yhchat.com/document/400-410
  - 批量发送消息: https://www.yhchat.com/document/400-421
  - 流式发送消息: https://www.yhchat.com/document/400-455
  - 编辑消息: https://www.yhchat.com/document/400-437
  - 撤回消息: https://www.yhchat.com/document/400-451
  - 消息列表: https://www.yhchat.com/document/400-450
  - 上传图片: https://www.yhchat.com/document/400-452
  - 上传视频: https://www.yhchat.com/document/400-453
  - 上传文件: https://www.yhchat.com/document/400-454

> 其他相关性小的 API 已省略.
