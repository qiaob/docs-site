# 架构

## 一张图

```
                    ┌──────────────────────────────────────────────────────────┐
  入口              │                     docstate.core                        │      存储端口（docstate.storage.base）
  ────              │  models.py   Document / Version / StateEntry / RepoBinding│      ──────────────────────────
  CLI ─────────┐    │  text.py     slug、分类规范化、摘要、忽略 frontmatter 的哈希│   DocumentStore ──► storage.sql   (SQLAlchemy + Alembic：SQLite / PostgreSQL / MySQL)
  HTTP API ────┼──► │  publish.py  发布用例：created / new_version / unchanged  │                 ──► storage.memory (测试、演示)
  MCP (独立包) ┤    │              update_meta / archive / 分类树 / 时间轴 / 搜索 │                 ──► 第三方 entry point `docstate.storage`
  import ──────┘    │  importer.py 仓库文件 → 文档                              │   StateStore    ──► 同上，或另一个库（DOCSTATE_STATE_URL）
                    │  checks.py   发布前检查        render.py  渲染 / CSP / bridge│
                    └────────────────────────────┬─────────────────────────────┘
                                                 │
  身份端口 docstate.auth：identity（none / fake / header）· tokens（命名 API token）· authorize（hook）
                                                 │
                    ┌────────────────────────────┴─────────────────────────────┐
                    │  docstate.server (Starlette)                              │
                    │  web.py 页面 · api.py JSON · app.py 组装 · i18n.py 文案   │
                    │  templates/ 壳页       core/static/docbridge.js 注入文档  │
                    └──────────────────────────────────────────────────────────┘
```

依赖方向只有一个：`server` → `core` + `storage` + `auth`；`storage` 适配器 → `core.models`；`core` 不依赖任何框架、数据库或模板引擎（渲染用的 Jinja 只处理文档本体的包装页）。

## 为什么是端口/适配器

- **可换数据库**：规则只写一遍（在 `core`），适配器只做读写。`tests/storage/test_contract.py` 是一套契约，memory、sqlite 都要过，`make test-pg` 让 PostgreSQL 也过；新后端通过了就是合格的。
- **文档与状态分开**：文档索引可以是静态的、可以来自 git；状态永远是动态写入。两个端口分开，才有「文档在 GitHub Pages，状态在 Cloudflare KV」这种部署（路线图）。
- **MCP 不碰数据库**：`docstate-mcp` 只调 HTTP API，所以它能装在 agent 那一侧，站点的权限、审计、限流只做一遍。

## 一次发布的旅程

```
agent / CLI / curl
   │  POST /api/publish {title, kind, category, content, slug?, dry_run?}
   ▼
api.publish ── auth.api_caller ─► 受信 token？→ 作者 = 转发的作者头 / token 名
   │                             否则读者身份 + authorize.require(PUBLISH)
   ├─ checks.warnings_for(store, content)      发布前检查（不写）
   │     dry_run → 返回 warnings
   ▼
core.publish.publish(store, PublishRequest)
   │  with store.transaction():
   │     get(slug) → 无：create(Document)，slug 唯一化
   │              → 有：比较 content_sha / body_sha → unchanged 直接返回
   │     add_version(Version)；update(doc.latest_version, updated_at)
   ▼
JSON {outcome, url, slug, version, warnings}
```

## 一次阅读的旅程

```
浏览器 GET /d/<slug>                 壳页：分类树、版本下拉、目录栏、<iframe sandbox src=/raw/<slug>/<n>>
   │
   ├─ GET /raw/<slug>/<n>             文档本体：Markdown 渲染成页面 / HTML 原样，注入 docbridge.js，
   │                                  响应头 CSP sandbox + frame-ancestors 'self'
   │
   └─ iframe ──postMessage──► 壳页    ready → ctx(slug, version, viewer)
                                       height → 壳页调整 iframe 高度（文档没有自己的滚动条）
                                       toc → 右侧目录
                                       state.get / state.set → 壳页 fetch /api/state/<slug>/<key>?scope=…
                                                                （带 X-Requested-With: docstate 防 CSRF）
                                       navigate → 壳页跳转站内链接
```

协议细节：[docbridge](protocol/docbridge.md)、[State API](protocol/state-api.md)。

## 存储层

```
docs            slug · title · category · tags_json · summary · status · kind · created_by · created_at · updated_at · latest_version · archived_at
doc_versions    doc_id → docs.id · version_no · label · content · text_plain · content_sha · size_bytes · source_path · created_by · created_at
doc_state       (slug, key, viewer) → value_json · updated_by · updated_at        viewer = "" 即 shared
repo_sync       slug → path · synced_version · synced_sha · meta_sha · pr_* · pending_* · deleted_at · last_error
```

- `doc_state` 以 `slug` 而不是 `doc_id` 为键，因此可以放在另一个数据库（`DOCSTATE_STATE_URL`）。
- 表名可加前缀（`DOCSTATE_DB_TABLE_PREFIX`）、PostgreSQL 可用独立 schema（`DOCSTATE_DB_SCHEMA`），与他人共库时用。
- 迁移用 Alembic，脚本在 `storage/sql/alembic/versions/`；`docstate migrate` 或启动时自动（`DOCSTATE_AUTO_MIGRATE=true`）。版本表名同样带前缀。
- 事务：`store.transaction()` 用 contextvar 把一个 Session 绑到当前上下文，块内的写共享它并一次提交；块外每个方法自成事务。

## 仓库目录

```
packages/docstate/src/docstate/
├── core/          models · text · clock · publish · importer · checks · render · templates/md_wrapper.html · static/docbridge.js
├── storage/       base（端口）· memory · sql/（models · store · migrate · alembic/）
├── auth/          identity · tokens · authorize
├── server/        app · web · api · deps · i18n · templates/
├── integrations/github/   client · repo_sync（可选的仓库回写）
├── settings.py    环境变量 + docstate.toml + profile
└── cli.py         serve · publish · import · migrate · check
packages/docstate-mcp/src/docstate_mcp/
├── client.py      HTTP API 客户端
├── server.py      FastMCP 工具与资源
└── __main__.py    docstate-mcp 命令
```

## 设计决策

见 [design/](design/)。0001 是从内部版本抽取成开源项目时的整体方案。
