# 发版流程

本文档描述 NextBridge 的版本发布方式：代码 tag、Docker 镜像、文档站三部分。

## 版本线与分支

| 分支 | 用途 | 部署位置 |
| --- | --- | --- |
| `main` | 最新稳定版 | 文档站生产域 `nextbridge.siiway.org` |
| `dev` | 开发集成分支 | 无文档部署；Docker 镜像 tag `unstable` |
| `vX.Y-legacy` | 已冻结的历史版本文档 | 文档站分支别名 `vX-Y-legacy.<project>.pages.dev` |

历史版本文档**不跟随代码 tag**，而是各自维护一条 `vX.Y-legacy` 分支。原因是 Cloudflare Pages 的 Git 集成只响应分支推送，无法从 tag 触发构建。

现有历史分支：

- `v0.3-legacy` → <https://v0-3-legacy.nextbridge.pages.dev>

> 分支名里的 `.` 在 Pages 别名中会被替换成 `-`，所以 `v0.3-legacy` 对应
> `v0-3-legacy`。命名务必带 `-legacy` 后缀：直接叫 `v0.3` 会和同名 git tag 冲突，
> Git 会报 `refname 'v0.3' is ambiguous`。

## 发布新版本

顺序是：写迁移页 → 改版本号 → 整理 CHANGELOG → 合并打 tag → 发 GitHub Release →
**发布之后**冻结文档。下面的小节按这个顺序排列，冻结在最后。

### 1. 写迁移页

每个版本都要有一页 `/{en,zh}/migrate`，路径固定（不带版本号）。新版本的迁移页在 `main` 上写，冻结时随文档一起进入 legacy 分支。

内容要求：

- 顶部用 `::: tip` 指向**上一个版本**的迁移页（例如 v0.4 的页面指向
  `https://v0-3-legacy.nextbridge.pages.dev/en/migrate`），让跨多个版本升级的用户
  能逐级迁移
- 列出：配置键改名/移除（对比上一版的实际 schema）、新增的 `global.*` 段、
  行为变更、升级后检查项
- 中英文各一份，`en/migrate.md` 与 `zh/migrate.md`

迁移页同时在侧边栏注册（`config.mts` 的 Guide 分组末尾）。

### 2. 更新版本号

```toml
# pyproject.toml
version = "0.5.0"
```

Docker CI 从这个字段推导镜像内的构建版本（取 `major.minor`）。

### 3. 整理 CHANGELOG 并用作 release 正文

`CHANGELOG.md` 平时只有 `## Unreleased`。发版时：

1. 把 `## Unreleased` 改名为 `## 0.5.0 - YYYY-MM-DD`
2. 在顶部补一个新的空 `## Unreleased`
3. **把这个版本段落的内容原样粘贴到 GitHub Release 正文里**

```sh
# 取出该版本段落，留作 release 正文（下一步用）
awk '/^## 0\.5\.0/{f=1} f&&/^## 0\.4\.0/{exit} f' CHANGELOG.md > /tmp/release-notes.md
```

遵循 [Keep a Changelog](https://keepachangelog.com/)。1.0 之前不做旧版本兼容，破坏性变更必须写清楚 —— release notes 是用户唯一的迁移依据。

### 4. 合并、打 tag、发 Release

```sh
# 通过 PR 合并到 main，标题形如 "v0.5 (#42)"
git checkout main && git pull
git tag v0.5
git push origin v0.5

# tag 推上去之后再发 Release，正文直接用上一步取出的 CHANGELOG 段落
gh release create v0.5 --title "v0.5" --notes-file /tmp/release-notes.md
```

**tag 推送会触发 Docker 版本镜像构建**（见下）。文档站不受 tag 影响 —— 文档是
`main` 分支推送时构建的，所以文档内容必须在 tag 之前就合进 `main`。

### 5. 验证

- <https://nextbridge.siiway.org/en/migrate> 是新版本的迁移页
- <https://nextbridge.siiway.org> 指向新版本内容
- <https://v0-3-legacy.nextbridge.pages.dev> 仍可访问，标题形如
  `xx | NextBridge Legacy v0.3`
- 旧链接 `https://nextbridge.siiway.org/en/v0.3/...` 正确 301 到历史分支
- 镜像仓库出现 `<major>.<minor>`、`<full version>` 两类 tag（`<major>` 从 v1 起）

### 6. 冻结文档（发版后做）

发版后把**该版本 tag 上的文档**冻结成历史分支（从 tag 开分支，代码与文档都停在发布那一刻）：

```sh
git checkout -b v0.4-legacy v0.4
```

> 历史 tag 的 `.gitignore` 里通常还写着 `docs/`（文档站迁入主仓库之前留下的）。
> 补上文档时需要 `git add -f docs`，或者顺手把那条忽略规则删掉。

在该分支上：

- `docs/.vitepress/config.mts`
  - `VERSION` 改为被冻结的版本号（如 `'v0.4'`）
  - `CURRENT_ORIGIN` 指向生产域（只写域名，不带版本号，发版时无需再改）
  - `sitemap.hostname` 改为该分支自己的别名
  - `editLink.pattern` 里的分支名改为 `v0.4-legacy`
  - `title` / `description` 保持 `NextBridge Legacy ${VERSION}` 模板即可，它会自动
    标注版本；nav 里的版本下拉同理只用 `Legacy ${VERSION}` 模板
- `docs/public/_redirects`
  - 本版路径 `/en/vX.Y/*` 重定向到去掉版本段的 `/en/:splat`
  - 更新版本的路径重定向到 `https://nextbridge.siiway.org/...`
  - 删掉本版不存在的页面条目
- 本地 `bun run build` 确认无死链后推送

**历史站的版本导航只引用最新版，不枚举版本列表。** 这样以后每次发版都不需要回头
修改每一条 legacy 分支 —— 它们永远指向 `CURRENT_ORIGIN`。

推送后 Pages 会自动创建分支部署，别名即可访问，无需在 dashboard 额外操作。

## 分支与部署速查

| 事件 | Pages 行为 | Docker CI |
| --- | --- | --- |
| push `main` | 生产部署 | 构建 `latest`、`main`、`<sha>-amd64/arm64` |
| push `dev` | 预览部署 | 构建 `unstable`、`dev`、`<sha>` |
| push `vX.Y-legacy` | 预览部署（分支别名） | 不触发 |
| push tag `vX.Y` | 无构建 | 构建 `X.Y`、`X.Y.Z`（`X` 仅 v1+） |
| PR | 预览部署 | 不触发（`pull_request` 触发被注释掉了） |
| 改 `docs/**` 或 `*.md` | 生产/预览部署 | 不触发（`paths-ignore` 已排除） |

## 手动测试 Docker 构建

`pull_request` 触发是**故意关闭**的，避免任何人通过开 PR 消耗构建额度。需要测试镜像时用下面任一方式，都只消耗自己的额度。

### 方式 A：`workflow_dispatch`（推荐，零改动）

workflow 已经有 `workflow_dispatch:`，可以直接指定**任意 ref**运行：

```sh
# 在 PR 源分支上跑
gh workflow run docker.yml --ref feat/my-branch

# 或者指定 PR 的 head
gh workflow run docker.yml --ref refs/pull/42/head

gh run list --workflow=docker.yml --limit 3
gh run watch
```

⚠️ 注意三点：

1. **workflow 文件必须已存在于该 ref 上**。如果你正在改 `docker.yml` 本身，需要先
   把改动推到分支，否则 `--ref` 指向的分支会用旧版定义（GitHub 从被指定的 ref 读取
   工作流定义，这一点和 `pull_request` 不同）。
2. dispatch 的 `github.event_name` 是 `workflow_dispatch`，不等于 `pull_request`，
   所以**会真的推镜像**，tag 为 `<branch>-<sha>`。测试时请确认分支名不会撞上
   `latest` / `unstable`。
3. 在 `main` 上手动 dispatch 会覆盖 `latest`，因为它命中了
   `enable={{is_default_branch}}`。想避免的话在**非 main 分支**上跑。

### 方式 B：本地构建，不推送

想验证 Dockerfile 能否构建时完全不必碰 CI：

```sh
docker buildx build --platform linux/amd64 --load -t nextbridge:test .
docker run --rm nextbridge:test python -c "import main"
```

### 方式 C：临时给 PR 开 `pull_request` 触发

如果要长期让 PR 验证镜像可构建（但不推送），可以在 workflow 里恢复：

```yaml
pull_request:
  branches: [main, dev]
```

代价是任何外部 PR 都会触发一次 amd64 + arm64 构建。若采用，建议再配合 `paths-ignore` 与 `concurrency` 限制并发。

## 文档站部署配置（Cloudflare Pages）

| 项 | 值 |
| --- | --- |
| 仓库 | `siiway/NextBridge` |
| 生产分支 | `main` |
| 根目录（Root directory） | `docs` |
| 构建命令 | `bun install && bun run build` |
| 输出目录 | `.vitepress/dist` |
| 预览分支 | `v*-legacy`（其余可设为 None 或排除 `dependabot/*`） |

`docs/public/_headers` 已给 `*.pages.dev` 加了 `X-Robots-Tag: noindex`，避免预览与历史版本被搜索引擎收录；生产域不受影响。

## 发布前的额外验证

`pytest` 只跑 SQLite，覆盖不到 PostgreSQL 和可选依赖缺失这两条路径。改动依赖版本、或改动 `services/db.py` 等 PostgreSQL 相关代码后，发版前必须手动跑完下面两项。

### 1. 真实 PostgreSQL 迁移

```sh
# 起一个临时实例
docker run -d --name nb-pg-test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=nb \
  -P postgres:16-alpine
docker port nb-pg-test          # 拿到映射到宿主的端口，下文以 <port> 代替
docker exec nb-pg-test pg_isready -U postgres

# 用真实 PG 跑一次启动迁移（会打印每一步 0-1 … 7-8）
mkdir -p /tmp/nb-pgtest
printf 'db_version: 0\n' > /tmp/nb-pgtest/meta.yaml
cd docs  # 或在仓库根跑，取决于你的工作目录
NEXTBRIDGE_DATA_PATH=/tmp/nb-pgtest uv run python -c "
import sys; sys.path.insert(0, '.')
from services import config as cfg
cfg.apply_raw({'database': {'url': 'postgresql://postgres:test@127.0.0.1:<port>/nb'}})
from services.db import init_db, db_target_version
init_db(); print('OK target=', db_target_version())
"

docker rm -f nb-pg-test
```

期望：日志里 `Applying migration 0 -> 1` 到 `7 -> 8` 全部出现，最后打印 `OK target= 8`，且引擎行显示 `postgresql+psycopg2`。

> 裸 `postgresql://` 会被自动改写为 `postgresql+psycopg2://`（SQLAlchemy 2.1 默认
> 驱动是 psycopg 3，本项目只装 psycopg2）。如果你改动了这段归一化逻辑，务必用裸
> URL 复测。

### 2. 无 libmagic 环境下的 driver import

CLI 启动时会 import 全部 driver 收集 `register_cli()` 钩子。任何顶层第三方导入都会让缺少该依赖的环境在启动时报错（WhatsApp 的 `neonize` 需要系统库 `libmagic`）。

```sh
docker run --rm -v "$PWD":/src:ro python:3.13-slim sh -c '
pip install -q uv 2>&1 | tail -1
cd /tmp && cp -r /src /tmp/app && cd /tmp/app && rm -rf .venv
uv sync --frozen --no-dev -q 2>&1 | tail -3
.venv/bin/python -c "
import importlib, pathlib
bad = []
for p in sorted(pathlib.Path(\"drivers\").glob(\"*.py\")):
    if p.name.startswith(\"_\") or p.stem == \"registry\":
        continue
    try:
        importlib.import_module(\"drivers.\" + p.stem)
    except Exception as e:
        bad.append((p.stem, type(e).__name__, str(e)[:80]))
print(\"failed:\", bad)
"
'
```

期望输出 `failed: []`。

## 已知限制

**历史版本无法自动跟随 tag。** 若将来需要「tag 即文档快照」，只能改用 Direct
Upload 项目 + CI 构建后 `wrangler pages deploy`，因为 Git 集成的项目不能切换成 Direct Upload。
