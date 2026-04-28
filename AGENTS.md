# NextBridge 开发

1. 请忽略本文档语言，跟随用户的语言回答
2. 项目使用 `uv` 作为包管理器，依赖须写入 `pyproject.toml` 而非 `requirements.txt` 或 `uv.lock`
3. 项目可用 lint/type check: `ruff check --fix` & `ruff format` & `ty check` (未在虚拟环境可能需要 `uv run ...`)
4. 在 增/删/改 功能时，同步修改对应的中文 & 英文文档部分 (`docs/` 下)
5. 在增加新 driver 时，需要在 `README.md` 的 `Special Thanks` 部分增加 driver 使用的库 (没有则不管)
6. 在达到 1.0 版本之前，不需要考虑代码的旧版本兼容性 (但是需要记忆下破坏性修改，以便在 release notes 中提及)

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
