# 0001 · 开源版架构设计

状态：**已采纳，阶段 0–2 已实现**（2026-09-22）· 起点是一个私有部署的文档站

采纳的决定：项目名 **Docstate**（包 `docstate` / `docstate-mcp`，CLI `docstate`，环境变量前缀 `DOCSTATE_`，JS API 仍是 `window.DocState`）；MIT；中文文档 + 双语 README；MCP 首版用命名 token + 配置作者；仓库回写保留为可选模块；SQL 适配器用 Alembic。下文写作时用的 `docsite` 均指 `docstate`。阶段 3（OIDC / 规则权限）、4（静态构建与 Cloudflare）、5（GitHub Action）尚未开始，见根 README 的路线图。

---

## 0. 背景与目标

它的前身解决的是一件事：**把 Markdown 或自包含 HTML 一次发布成固定 URL 的文档，同址追加版本，并让文档自己能存状态。** 其中两点在市面上的文档站（MkDocs、Docusaurus、Notion 类）里都没有很好的对应物：

1. **HTML 文档一等公民**：AI 生成的交互式 HTML（图表、看板、检查清单）不用改一行就能发布，跑在 CSP `sandbox` 的 iframe 里，拿不到读者 cookie，只能经 postMessage 请壳页代办。
2. **文档内状态（DocState）**：文档里的勾选、备注、排序可以按读者（`me`）或全员（`shared`）存到服务端，跨设备、跨版本；Markdown 的任务列表不用写代码就自动保存。

### 0.1 定位：市面上没有的是「组合」

能给一个 HTML 文件发 URL 的产品很多（Tiiny.host、Netlify Drop、GitHub Pages），企业里也有发布 HTML 报告的自托管产品（Posit Connect：每个版本独立 URL、按用户组授权），AI 平台自己也能把交互 HTML 发成链接并带状态（Claude Artifacts）。Wiki 类（Wiki.js、Confluence、Notion）对 HTML 要么净化掉脚本、要么只能 embed 一个 iframe，安全靠信任编辑者而不是隔离。没有一个产品同时做到：

- Markdown 与 HTML **同一套**分类、版本、搜索、URL 规则；
- 带脚本的 HTML 在 **沙箱** 里跑，任何人（包括 AI）发布都不威胁站点会话；
- 文档不写后端就有 **状态**（按读者 / 全员）；
- **agent 原生**的发布路径：MCP 一条调用拿 URL，与 git 双向同步；
- **自托管**、可换数据库、可上静态托管。

README 的一句话往这里写：把 Markdown 和交互式 HTML 当作有版本、有权限、会记状态的文档发布给团队，自己托管，AI 一条调用就能发。

开源版的目标：

| 目标 | 具体含义 |
|---|---|
| 可扩展 | 存储、身份、权限、发布渠道、托管平台都是可插拔的端口，第三方能不改核心加后端 |
| 易维护部署 | 一个镜像、一条 `pip install`、compose / k8s / Fly 现成清单；配置全走环境变量 + 可选配置文件；多环境 profile |
| 支持静态托管 | GitHub Pages、Cloudflare Pages 这类只能放静态文件的平台也能跑：站点构建成静态产物，状态存储换成一个很小的外部后端 |
| 文档完整 | 架构、协议、部署、扩展、写作指南、ADR，让别人能读懂并接手 |

首版**不做**：在线富文本编辑、评论、多租户、全文分词搜索引擎（先用 SQL LIKE / 客户端索引）。

---

## 1. 现状盘点

### 1.1 模块与职责（起点约 3.5k 行 Python）

| 模块 | 行数 | 职责 | 开源版去向 |
|---|---|---|---|
| `service.py` | 486 | 发布 / 版本 / 列表 / 搜索 / 分类树 / 时间轴 / 状态；**领域逻辑与 SQLAlchemy 查询混在一起** | 拆成 `core/`（纯领域）+ `storage/sql/`（持久化） |
| `db.py` | 223 | 4 张表（docs / doc_versions / doc_state / repo_sync）、engine、`create_all` + 补列 | `storage/sql/models.py` + Alembic 迁移 |
| `render.py` | 301 | markdown-it 渲染、wikilink、相对链接改写、CSP 常量、bridge 注入、正文提取 | `core/render/`，几乎原样保留 |
| `importer.py` | 224 | 仓库文件 → 文档（目录=分类、文件名=slug、frontmatter=元信息） | `core/importer.py`，原样保留 |
| `web.py` / `api.py` | 235 / 417 | 页面路由 / JSON 接口 | `server/`，改为依赖端口而非 Session |
| `auth.py` / `authz.py` | 124 / 201 | fake / 网关专用模式 / header；外部权限服务客户端 | `auth/`：端口化；网关模式泛化为 header+secret；权限客户端换成 hook |
| `repo_sync.py` / `github.py` | 463 / 222 | 站点 → GitHub 仓库回写（PR、App 鉴权、dispatch 模式） | `integrations/github/`，可选功能 |
| `mcp_tools.py` | 165 | FastMCP `docs_*` 工具 | `integrations/mcp/`，可选依赖 `docsite[mcp]` |
| `checks.py` | 83 | 发布前检查（相对链接、外链 CDN 白名单） | `core/checks.py` |
| `templates/` + `static/docbridge.js` | ~1k | 壳页、md 包装页、目录树、bridge 协议 | 保留；**服务端渲染与静态构建共用同一套模板** |
| `scripts/seed.py` / `pub.py` / `repo_sync.py` | 280 | 命令行入口 | 合并成一个 `docsite` CLI |
| `tests/` | ~1.5k | 74 个测试（SQLite 临时库） | 保留并改造成「同一套契约测试跑所有存储适配器」 |

### 1.2 抽取时移除的部署耦合

起点代码带着它原来那个部署环境的痕迹：品牌与邮箱域、网关专用的身份协议、只在那套集群里成立的 CI/CD 与清单、对某个特定文档仓库的路径假设。这些都不是产品的一部分，抽取时全部删除或参数化（站名、邮箱域、登录代理头、token、工作流名都变成配置），并且**不带 git 历史**：开源仓库从一个干净的提交开始。

---

## 2. 总体架构：核心 + 端口/适配器

```
                       ┌────────────────────────────────────────────────────┐
  发布渠道             │                     docsite core                   │        存储端口
  ─────────            │  domain: Document / Version / StateEntry / Category │        ────────
  CLI  ───────┐        │  render: markdown-it · bridge 注入 · CSP · 正文提取 │   DocumentStore ──► sql (SQLite/PG/MySQL)
  HTTP API ───┼──────► │  importer: 仓库文件 → 文档（目录=分类，frontmatter）│                 ──► memory (测试)
  MCP  ───────┤        │  checks: 发布前检查                                 │                 ──► fs / git (只读，静态构建)
  GitHub Action┘       │  publish 用例: created / new_version / unchanged    │   StateStore    ──► sql
                       └───────────────┬───────────────────┬────────────────┘                 ──► redis (可选)
                                       │                   │                                  ──► HTTP State API
  身份端口   Authenticator: none · fake · header(+secret) · oidc                                   (Cloudflare Pages Function / Worker + KV)
  权限端口   Authorizer:    allow-all · domain · rules.yaml · 第三方 entry point
                                       │                   │
                    ┌──────────────────┴──┐          ┌─────┴────────────────────┐
                    │  server (Starlette) │          │  build (静态站生成器)    │
                    │  壳页 · /raw · /api │          │  dist/ = 壳页 + raw 文档 │
                    │  动态模式，全部功能 │          │  + JSON 索引 + 客户端搜索│
                    └─────────────────────┘          └──────────────────────────┘
                     Docker / k8s / Fly / PaaS         GitHub Pages / Cloudflare Pages / 任何静态托管
```

两条交付形态共用 core 与 Jinja 模板，区别只在「谁来回答请求」：

| | Server 模式 | Static 模式 |
|---|---|---|
| 文档来源 | 任何渠道发布进 DocumentStore | git 仓库目录（构建时读取） |
| 版本 | 每次发布追加 | 首版只有最新版；可选从 git 历史生成版本列表 |
| 搜索 | SQL LIKE（后续可换全文索引） | 构建时生成 JSON 索引，浏览器端 MiniSearch |
| 状态（DocState） | StateStore | 外部 State API（Cloudflare Pages Function / Worker），没有配置时退化为浏览器本地存储 |
| 身份 | Authenticator 端口 | 平台提供（Cloudflare Access 头），或匿名 viewer id |

### 2.1 目录结构（目标）：一个仓库，三个可独立发布的包

uv workspace 单仓多包。站点、MCP 服务器、Cloudflare 状态后端各自版本化发布，但共享 CI、文档和示例。

```
docsite/
├── packages/
│   ├── docsite/                 # PyPI: docsite —— 站点本体
│   │   └── src/docsite/
│   │       ├── core/            # 领域模型（dataclass）、slug、摘要、body_sha、importer、checks、render/
│   │       ├── storage/         # base.py（DocumentStore / StateStore 协议）、sql/（models、adapter、alembic/）、memory.py、fs.py
│   │       ├── auth/            # base.py（Authenticator / Authorizer 协议）、none.py、fake.py、header.py、oidc.py、rules.py
│   │       ├── server/          # Starlette app：web.py、api.py、templates/、static/、i18n
│   │       ├── build/           # 静态站生成器 + platforms/（github_pages.py、cloudflare.py 产出 _headers / functions）
│   │       ├── integrations/github/   # 仓库回写、Action 辅助（可选）
│   │       ├── settings.py      # pydantic-settings：环境变量 + docsite.toml + profile
│   │       └── cli.py           # docsite serve | build | publish | import | migrate | check
│   ├── docsite-mcp/             # PyPI: docsite-mcp —— 独立 MCP 服务器，见 §8.1
│   │   └── src/docsite_mcp/     # server.py、client.py、tools.py、resources.py
│   └── state-api-cloudflare/    # npm: @docsite/state-api-cloudflare —— Pages Function / Worker（JS）：State API on KV
├── deploy/                      # docker-compose（sqlite / postgres）、kubernetes（kustomize）、fly/
├── .github/workflows/           # ci（lint + test 矩阵 SQLite/PG）、release（GHCR + PyPI + npm）、docs（用 docsite 自己发布文档到 Pages）
├── docs/                        # 见 §11
├── examples/                    # 一个示例文档仓库（Markdown + 交互 HTML）+ 各 MCP 客户端的配置片段
└── tests/                       # 契约测试对每个存储适配器各跑一遍；MCP 端到端测试
```

---

## 3. 领域模型（不变的部分）

```python
@dataclass(frozen=True)
class Document:
    slug: str; title: str; category: str; tags: tuple[str, ...]; summary: str
    status: Literal["draft", "review", "approved", "deprecated"]; kind: Literal["md", "html"]
    created_by: str; created_at: datetime; updated_at: datetime
    latest_version: int; archived_at: datetime | None

@dataclass(frozen=True)
class Version:
    doc_slug: str; no: int; label: str; content: str; text_plain: str
    content_sha: str; size_bytes: int; source_path: str | None; created_by: str; created_at: datetime

@dataclass(frozen=True)
class StateEntry:
    doc_slug: str; key: str; viewer: str   # viewer == "" 即 shared 作用域
    value: Any; updated_by: str; updated_at: datetime
```

保留的语义：同 slug 再发布 = 新版本；正文哈希忽略 frontmatter（仓库回写加的 frontmatter 推回来不算新版本）；归档是软删除，URL 继续可访问；分类 = 目录路径；`source_path` 把仓库文件和文档绑定。

---

## 4. 存储抽象

### 4.1 两个端口，而不是一个

文档索引与文档状态的部署故事不同：文档可以来自 git、可以是静态的；状态永远是动态写入。拆开以后，静态站才能「文档在 GitHub Pages，状态在 Cloudflare KV」。

```python
class DocumentStore(Protocol):
    def get(self, slug: str) -> Document | None: ...
    def get_version(self, slug: str, no: int | None) -> Version | None: ...
    def versions(self, slug: str) -> list[Version]: ...
    def list(self, q: DocQuery) -> list[Document]: ...        # category/tag/status/q/limit
    def tree(self) -> list[CategoryNode]: ...
    def timeline(self, category: str | None, limit: int) -> list[Version]: ...
    def search(self, q: str, limit: int) -> list[SearchHit]: ...
    def by_source_path(self, path: str) -> Document | None: ...
    def publish(self, draft: PublishRequest) -> PublishResult: ...   # created | new_version | unchanged
    def update_meta(self, slug: str, **fields) -> Document: ...
    def archive(self, slug: str) -> Document: ...

class StateStore(Protocol):
    def get(self, slug: str, key: str, viewer: str) -> StateEntry | None: ...
    def set(self, slug: str, key: str, viewer: str, value: Any, by: str) -> StateEntry: ...
```

`publish` 的 unchanged 判定、slug 生成、分类规范化这些规则放在 `core`，适配器只负责读写；这样每个适配器都薄，规则只有一份。

### 4.2 适配器

| 适配器 | 覆盖 | 说明 |
|---|---|---|
| `sql` | DocumentStore + StateStore | SQLAlchemy 2.x；URL 决定方言：`sqlite://`、`postgresql://`（psycopg 3）、`mysql://`（可选依赖）。保留表前缀 / schema 选项（与他人共库）。迁移改用 **Alembic**（现在的 `create_all` + 补列在多方言下不够） |
| `memory` | 两者 | 测试与演示 |
| `fs` / `git` | DocumentStore（只读） | 从目录读取文档（复用 importer 规则），静态构建的输入；`git` 变体从提交历史生成版本列表 |
| `redis` | StateStore | 可选；状态量小、写频繁的场景 |
| HTTP State API | StateStore（远端） | 不是 Python 适配器，而是一份**协议**（§6.2）：任何实现了它的服务都能当状态后端。仓库内提供 Cloudflare 实现 |

选择方式：按 URL scheme 解析，未知 scheme 查 entry point，第三方 `pip install docsite-storage-dynamo` 即可接入。

```toml
[project.entry-points."docsite.storage"]
sql = "docsite.storage.sql:SqlStorage"
memory = "docsite.storage.memory:MemoryStorage"
```

```bash
DOCSITE_STORAGE_URL=postgresql://user:pw@host/db     # 文档索引
DOCSITE_STATE_URL=redis://host:6379/0                # 状态；不填则与 STORAGE 同库
```

### 4.3 契约测试

`tests/storage/contract/` 一套测试，用 fixture 参数化跑 `sql[sqlite]`、`sql[postgres]`（CI 起 PG 服务）、`memory`。新适配器只要通过契约测试就是合格的，这是「方便扩展」最实在的保障。

---

## 5. 身份与权限

### 5.1 Authenticator（谁在看）

| 模式 | 用途 | 来源 |
|---|---|---|
| `none` | 公开站，匿名读者；`me` 作用域用浏览器生成的匿名 id | 新增 |
| `fake` | 本地开发，顶栏切换身份 | 保留 |
| `header` | 信任登录代理写入的邮箱头；可选校验一个共享密钥头（防止绕过代理直连） | 泛化自起点的两种代理模式。预设：`cloudflare-access`、`oauth2-proxy`、`tailscale` |
| `oidc` | 站点自己登录：Google / GitHub / Okta / 任意 OIDC，`authlib` 实现，会话 cookie | 新增 |

### 5.2 Authorizer（能做什么）

权限点保留三个：`read` / `publish` / `admin`。

| 模式 | 说明 |
|---|---|
| `allow-all` | 默认；登录即可读、可发 |
| `domain` | 邮箱域白名单（`DOCSITE_ALLOWED_DOMAINS`） |
| `rules` | `rules.yaml`：按邮箱 / 域 / 分类前缀授予 read / publish / admin |
| entry point | 第三方接自家权限服务（一个私有 fork 可以把自己的权限客户端做成这样一个插件） |

### 5.3 服务间调用

`/api/publish`、`/api/import`、`/api/repo-sync/pending` 给 GitHub Action、MCP 网关这类受信服务用。保留「共享密钥头 + 转发的作者邮箱」模型，密钥改为可配置多枚、可命名（`DOCSITE_API_TOKENS=ci:xxx,agent:yyy`），审计日志记 token 名。

---

## 6. 渲染与安全模型（保留，并写成公开协议）

### 6.1 沙箱

- `/raw/<slug>/<n>` 带 CSP：`sandbox`（无 `allow-same-origin`）+ `frame-ancestors 'self'` + 外链脚本白名单（cdnjs / jsdelivr）。
- 壳页只认自己 iframe 的消息，只代理当前文档的状态。
- 状态写接口要求 `X-Requested-With: docsite`（跨站表单发不出自定义头，即 CSRF 防护）。
- 静态托管拿不到响应头时（GitHub Pages）：iframe 的 `sandbox` 属性仍然生效（这是 opaque origin 的来源，也是真正承重的一层）；外链白名单退化为 raw 文档里的 `<meta http-equiv="Content-Security-Policy">`；Cloudflare / Netlify 用 `_headers` 文件恢复完整响应头。构建器按平台产出。

### 6.2 State API 协议（新文档 `docs/protocol/state-api.md`）

```
GET  /api/state/{slug}/{key}?scope=me|shared           → {key, scope, value, updated_by, updated_at}
PUT  /api/state/{slug}/{key}?scope=me|shared  {value}  → 同上        需要头 X-Requested-With: docsite
身份：会话（server 模式）· Cf-Access-Authenticated-User-Email（Cloudflare Access）· X-Docsite-Viewer 匿名 id
限制：value ≤ 64KB，key 匹配 ^[\w.\-:]{1,200}$
```

壳页对状态后端的依赖只有这两个请求，所以后端可以是本站、可以是 Cloudflare Pages Function、也可以是别人写的任何东西。

### 6.3 docbridge 协议（新文档 `docs/protocol/docbridge.md`）

文档 ↔ 壳页的 postMessage 消息：`ready / ctx / state.get / state.set / reply / height / toc / navigate / wheel / remeasure`。写清楚以后，别的壳（比如嵌到 Notion、嵌到别的站）也能承载这些文档。

---

## 7. 静态模式与托管平台

### 7.1 `docsite build`

```bash
docsite build --source ./docs --out ./dist --base-url https://docs.example.com \
              --state-api https://docs.example.com/api/state    # 可省略 → 浏览器本地存储
```

产物：

```
dist/
├── index.html                 # 首页（最近更新 + 根 README）
├── c/<category>/index.html    # 分类页
├── t/index.html               # 时间轴
├── d/<slug>/index.html        # 文档壳页
├── raw/<slug>/<n>.html        # 沙箱内的文档本体（含 bridge、meta CSP）
├── search/index.json          # 标题 / 摘要 / 标签 / 正文（截断）
├── api/docs.json, api/categories.json   # 与 server 模式同形的只读接口，方便 MCP / 脚本
└── _headers                   # Cloudflare / Netlify 的响应头（CSP）
```

模板复用：Jinja 模板加一层 `UrlBuilder`（server：`/d/x`，static：`/d/x/`），路由函数变成「给上下文 → 渲染」的纯函数，server 与 build 各自调用。

### 7.2 平台

| 平台 | 文档托管 | 状态后端 | 身份 |
|---|---|---|---|
| GitHub Pages | 工作流模板 `docsite/.github/workflows/pages.yml`：push → `docsite build` → 部署 | 外部 State API URL，或浏览器本地存储 | 匿名 |
| Cloudflare Pages | 同上 + `wrangler pages deploy dist` | **同源** Pages Function `functions/api/state/[slug]/[key].js`，KV 绑定（推荐首选：无 CORS、无额外域名） | Cloudflare Access 头（可选） |
| Cloudflare Worker（独立） | 任意静态托管 | Worker + KV / D1，CORS 白名单 | 同上 |
| Netlify / Vercel | 类似 GitHub Pages | 外部 State API | 匿名 |

### 7.3 版本、搜索、时间轴

- 首版静态模式：只有最新版；文档页「版本历史」链到 GitHub 的 `commits/<path>`。第二步：`--versions git` 用 `git log --follow` 生成版本页。
- 搜索：MiniSearch（jsdelivr）读 `search/index.json`；索引大小按正文截断（每篇 2KB 可调）。
- 时间轴：文件的 frontmatter 日期 → 文件名日期 → git 提交时间。

---

## 8. 发布渠道

| 渠道 | 形态 |
|---|---|
| CLI | `docsite publish <file> --category x`、`docsite import <dir>`（对应现有 `pub.py` / `seed.py`） |
| HTTP | `/api/publish`、`/api/import`、`/api/docs*`（保留） |
| MCP | 独立子包 `docsite-mcp`，见 §8.1：装在 agent 那一侧，对着任何一个站点的 HTTP API 工作 |
| GitHub Action | `action.yml`：文档仓库 push 后，server 模式 POST 变更文件到 `/api/import`；static 模式跑 `build` 并部署 |
| 仓库回写 | `integrations/github`：可选，配置了仓库与凭据才启用；保留 direct / dispatch 两种模式 |

### 8.1 MCP 子包 `docsite-mcp`

现状：`mcp_tools.py` 里的 FastMCP 应用直接调服务层、直连数据库，挂在站点进程的 `/mcp` 上，默认关闭，只当本地开发用；作者写死在 `DOCSITE_MCP_AUTHOR`。这样它离不开站点进程，也没法装到用 Claude Code / Cursor 的那台机器上。

开源版把它拆成**独立的包和进程**，只依赖站点的 HTTP API：

```
   Claude Code / Claude Desktop / Cursor / Codex CLI            站点（任意部署）
   ─────────────────────────────────────────────                ────────────────
   MCP client ──stdio──► docsite-mcp（本机进程）──HTTPS + token──► /api/publish
                          读本地文件 path=…                        /api/docs …
```

**为什么是独立包**

- agent 在哪，MCP 服务器就装在哪：`uvx docsite-mcp` 一行，不需要站点开任何额外端口；`path=` 读的是**本机文件**（现在是站点侧挂载目录的相对路径，很别扭）。
- 站点只暴露一套 HTTP API，权限、审计、限流都只做一遍；MCP 是它的一个客户端，与 CLI、GitHub Action 同级。
- 站点包不背 `fastmcp` 依赖；MCP 包也不背 SQLAlchemy。两边独立发版。
- 一个统一的 MCP 网关同样可以用「调 HTTP API」的方式包住这个包，形态一致。

**工具集**（都带 `readOnlyHint / destructiveHint / idempotentHint` 注解）

| 工具 | 说明 |
|---|---|
| `docs_publish(title, category, content \| path, kind?, slug?, tags?, summary?, label?, status?)` | 发布或追加版本，返回 URL、版本号、outcome 与发布前检查的 warnings；`path` 是本机文件 |
| `docs_check(content \| path, kind?)` | 只做发布前检查（相对链接、外链 CDN 白名单、`[[wikilink]]` 是否存在），不写 |
| `docs_list(category?, tag?, q?, status?, limit?)` | 列表，最新在前 |
| `docs_search(q, limit?)` | 全文搜索（服务端补 `/api/search`） |
| `docs_get(slug, version?, include_content?)` | 元信息，可带正文 |
| `docs_versions(slug)` | 版本历史 |
| `docs_categories()` | 分类树 |
| `docs_update_meta(slug, …)` | 改标题 / 分类 / 标签 / 摘要 / 状态，不产生版本 |
| `docs_archive(slug)` | 归档（需要 admin），`destructiveHint: true` |

MCP **resources**：`docs://{slug}` 与 `docs://{slug}/v/{n}` 直接读正文，agent 引用一篇已发布文档时不用先调工具。

**身份**：`DOCSITE_URL` + `DOCSITE_TOKEN`（站点侧的命名 API token，§5.3）；作者取 `DOCSITE_AUTHOR`，没有则用 token 的名字。HTTP 传输模式下的按人授权走 MCP 规范的 OAuth，列为后续。

**两种运行方式，一份代码**

- 独立进程（默认）：`docsite-mcp --transport stdio`，或 `--transport http --port 9000` 给远程 agent 用。
- 进程内挂载：`docsite serve --mcp` 把同一个 FastMCP 应用挂在 `/mcp`，工具通过 `httpx.ASGITransport` 调自己的 API，所以没有第二条代码路径；单容器部署时省一个进程。

**客户端配置片段**放在 `examples/mcp/`：

```bash
claude mcp add docsite -e DOCSITE_URL=https://docs.example.com -e DOCSITE_TOKEN=… -- uvx docsite-mcp
```

Claude Desktop / Cursor / Codex CLI 各给一份 JSON。

---

## 9. 配置与环境

- 一切可配置项都是 `DOCSITE_*` 环境变量（pydantic-settings），密钥只走环境变量。
- 可选 `docsite.toml`：非密钥配置（站名、语言、分类显示名、构建选项），并支持 profile：

```toml
[site]
title = "My Docs"
lang = "en"            # UI 语言：en / zh-CN
base_url = "http://localhost:8787"

[storage]
url = "sqlite:///data/docsite.db"

[auth]
mode = "fake"

[profiles.staging]
site.base_url = "https://docs.staging.example.com"
auth.mode = "header"
auth.header = "Cf-Access-Authenticated-User-Email"

[profiles.prod]
site.base_url = "https://docs.example.com"
auth.mode = "oidc"
```

优先级：环境变量 > `DOCSITE_PROFILE` 选中的 profile > 文件默认段 > 代码默认值。`docsite check` 打印解析后的配置（隐去密钥）与后端连通性，部署排障第一步。

---

## 10. 部署与发布工程

- **产物**：GHCR 镜像 `ghcr.io/<owner>/docsite:<version>`（tag 触发）、PyPI 包（`pipx run docsite serve`）。
- **deploy/**：`docker-compose.sqlite.yml`、`docker-compose.postgres.yml`；`kubernetes/`（kustomize base + 一个示例 overlay，PVC 版与 PG 版）；`fly/fly.toml`。
- **CI（GitHub 托管 runner）**：lint（ruff + black + isort）、pytest 矩阵（SQLite、PostgreSQL service）、镜像构建；`release.yml` 发 GHCR + PyPI；`docs.yml` 用 `docsite build` 把 `docs/` 发布到本项目的 GitHub Pages（自举，也是最好的示例）。
- **本地**：保留 `make up/test/lint/fmt`（Docker），另加 `uv run docsite serve` 的纯本地路径，降低贡献门槛。

---

## 11. 文档规划（中文先行，README 双语）

```
README.md / README.zh-CN.md        一屏说清是什么、三分钟跑起来、截图
docs/
├── getting-started.md             安装 → 发布第一篇 → 一篇带状态的 HTML
├── concepts.md                    文档 / 版本 / 分类 / 状态作用域 / 沙箱
├── architecture.md                本文精简版 + 请求时序图（壳页 ↔ iframe ↔ State API）
├── configuration.md               全部配置项参考表
├── deployment/docker.md · kubernetes.md · fly.md
├── platforms/github-pages.md · cloudflare-pages.md · cloudflare-worker.md
├── extending/storage-backend.md · auth-backend.md · renderer.md · theming.md
├── protocol/state-api.md · docbridge.md · http-api.md · mcp.md
├── writing/markdown.md（表格、任务列表、mermaid、wikilink、相对链接）· html-docstate.md（DocState API）
├── security.md                    威胁模型、CSP、CSRF、静态托管的退化说明
├── design/                        本 ADR 及后续决策
└── CONTRIBUTING.md · CHANGELOG.md · SECURITY.md · LICENSE
```

---

## 12. 实施阶段

| 阶段 | 内容 | 验收 |
|---|---|---|
| **0 落地脱敏** | 删除 §1.2 的部署耦合；网关模式 → `header+secret`；权限客户端 → hook；品牌 / 默认邮箱 / 文案参数化；UI 文案抽成 i18n（en / zh-CN）；GitHub 托管 CI；LICENSE | `uv run docsite serve` 与 `make up` 都能不依赖公司资源跑起来，74 个测试绿 |
| **1 存储抽象** | `core/` 与 `storage/` 拆分；`DocumentStore` / `StateStore`；sql + memory 适配器；Alembic；契约测试；URL scheme + entry point 选择 | 契约测试对 sqlite / postgres / memory 全绿；旧接口行为不变 |
| **2 MCP 子包** | workspace 拆包；`docsite-mcp` 独立进程（stdio / http）+ 进程内挂载；工具集与 resources；服务端补 `/api/search`、命名 token；`examples/mcp/` 客户端配置 | Claude Code 通过 `uvx docsite-mcp` 对着本地站点发一篇文档拿到 URL；端到端测试覆盖每个工具 |
| **3 身份权限** | Authenticator / Authorizer 端口；none / fake / header / oidc；domain / rules | 各模式各有测试；`docsite check` 能报出配置 |
| **4 静态构建与平台** | `docsite build`；UrlBuilder；客户端搜索；GitHub Pages 工作流；Cloudflare Pages Function（KV）；`_headers` / meta CSP | 示例仓库能部署到 GitHub Pages 与 Cloudflare Pages，DocState 在 Cloudflare 上可用 |
| **5 发布集成** | 统一 CLI；GitHub Action；回写模块泛化 | Action 在示例仓库跑通 |
| **6 文档** | §11 全部 | 文档站自举发布 |
| **7 发布 v0.1.0** | GHCR + PyPI（两个包）+ npm + Release Notes | — |

阶段 0 完成后每个阶段单独提 PR。阶段 2 只依赖 HTTP API，可与阶段 1 并行；顺序上先做 0 → 1 → 2 → 4（可换 DB、MCP、能上 Pages 是最想要的三件事），3 与 5 穿插。

---

## 13. 需要你拍板的事

1. **项目名**：沿用 `docsite`（包名、CLI、环境变量前缀都已是它），还是换一个更有辨识度的（备选：`docshelf`、`livedocs`、`pagestate`）？影响目录名、PyPI 名、GHCR 名。
2. **许可证**：建议 MIT（最省心）；Apache-2.0 带专利条款也可。
3. **文档语言**：建议中文先行、README 双语，英文详细文档随后补；还是英文为主？
4. **Cloudflare 方案**：优先做 Pages Function（同源，最省事），独立 Worker 作为第二选项？
5. **仓库回写**是否进首版：功能完整但 460 行、流程重，建议保留为可选模块，不进阶段 0–3 的关键路径。
6. **迁移工具**：sql 适配器引入 Alembic（建议是；否则多方言下补列逻辑会越来越脆）。
7. **MCP 的作者身份**：首版用「命名 token + `DOCSITE_AUTHOR`」（简单、够用），按人 OAuth 授权放到后续；可以接受吗？

确认后从阶段 0 开始，第一步是把当前复制件做成基线提交，之后所有改动都能 diff 出来。
