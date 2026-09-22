# Docstate

**把 Markdown 和交互式 HTML 当作有版本、会记状态的文档发布给团队。自己托管，AI 一条 MCP 调用就能发。**

[English](README.md) · [文档目录](docs/README.md) · [MCP 服务器](docs/mcp.md) · [架构](docs/architecture.md)

Docstate 是一个很小的文档站，核心只有一个想法：一篇文档可以是 Markdown，也可以是一个**自包含的 HTML 页面**——AI 帮你写的图表、检查清单、看板——两种都拿到固定 URL、版本历史、在分类树里的位置，以及**状态**：勾选、备注、排序可以按读者或者全员保存，作者不用写任何后端。

```text
   Markdown / HTML  ──►  /d/<slug>   固定 URL，同址追加版本
                         沙箱隔离:   文档跑在隔离的 iframe 里，拿不到读者 cookie
                         有状态:     window.DocState.get / set，按读者或全员共享
                         有组织:     目录式分类、时间轴、搜索
                         agent 原生: MCP 工具发布与读取；git 可以是唯一来源
```

## 为什么

| 你想… | 通常的下场 | Docstate |
|---|---|---|
| 把一份交互式 HTML 报告分享给团队 | 丢进聊天，或者托管在一个没有版本、没有索引的地方 | 它就是一篇普通文档：有 URL、版本、分类 |
| 让 AI agent 发布它写好的东西 | 复制粘贴 | `docs_publish` 直接返回 URL；dry run 先告诉它哪里会坏 |
| 在文档里放一个检查清单 | 一刷新就没了 | `DocState.set("checklist", …)` 按读者或全员持久化 |
| 数据在自己手里 | SaaS 拿着你的文档 | 一个容器，SQLite 或 PostgreSQL，前面放你自己的登录代理 |

文档运行在 CSP `sandbox` 的 iframe 里（opaque origin）：读不到读者 cookie，也调不了站点接口，只能通过一小套 `postMessage` 协议请持有会话的壳页代办。这就是「任何人（包括模型）都能发布带脚本的 HTML」仍然安全的原因。

## 三分钟跑起来

```bash
pip install "docstate[postgres]"     # 或 uv tool install docstate
docstate serve                       # http://localhost:8787，SQLite 在 ./data
docstate import ./docs               # 把一个目录的 .md / .html 发布进去
```

用 Docker：

```bash
git clone https://github.com/qiaob/docs-site && cd docstate
make up && make import               # 站点 + 示例文档
```

打开 http://localhost:8787。顶栏可以切换演示读者（`fake` 身份模式），看看 `/d/docstate-demo` 和 `/d/interactive-lab` 里按读者保存的状态。

## 发布

```bash
# 发一个文件（走 HTTP API）
docstate publish report.html --category analytics/reports --label "补充 6 月数据"
# 直接调接口
curl -s localhost:8787/api/publish -H 'Content-Type: application/json' \
  -d '{"title":"Hello","kind":"md","category":"guides","slug":"hello","content":"# Hello"}'
```

同一个 slug 再发就是新版本，内容没变返回 `unchanged`。`dry_run: true` 只返回发布前检查的 warnings（会 404 的相对链接、会被沙箱拦下的脚本、找不到目标的 `[[wikilink]]`）。

### 从 AI agent 发（MCP）

```bash
claude mcp add docstate -e DOCSTATE_URL=https://docs.example.com -e DOCSTATE_TOKEN=… -- uvx docstate-mcp
```

[`docstate-mcp`](packages/docstate-mcp) 装在 agent 那一侧，对着站点的 HTTP API 工作。工具：`docs_publish`、`docs_check`、`docs_list`、`docs_search`、`docs_get`、`docs_versions`、`docs_categories`、`docs_update_meta`、`docs_archive`；资源 `docs://{slug}`。详见 [docs/mcp.md](docs/mcp.md)。

## 文档里怎么存状态

```js
await DocState.get("checklist", { scope: "me" });                 // 按读者，跨设备
await DocState.set("checklist", { 0: true }, { scope: "me" });
await DocState.set("note", { text: "..." }, { scope: "shared" }); // 全员一份
DocState.subscribe("note", v => render(v), { scope: "shared" });  // 轮询同步他人改动
```

Markdown 不用写代码：任务列表 `- [ ]` 的勾选自动保存，默认按读者各存一份，frontmatter 加 `task_scope: shared` 变全员共享。

## 配置

一切可配置项都是 `DOCSTATE_` 前缀的环境变量；可选的 `docstate.toml` 放非密钥配置和按环境的 profile。最重要的几个：

| 变量 | 默认 | |
|---|---|---|
| `DOCSTATE_STORAGE_URL` | `sqlite:///data/docstate.db` | `postgresql://…`、`mysql://…`、`memory://` |
| `DOCSTATE_STATE_URL` | 同 storage | 把文档状态放到另一个库 |
| `DOCSTATE_AUTH_MODE` | `fake` | `none`（公开站）、`fake`（本地开发）、`header`（登录代理后面） |
| `DOCSTATE_API_TOKENS` | | `ci:…,agent:…`，API 与 MCP 的受信调用方 |
| `DOCSTATE_SITE_TITLE`、`DOCSTATE_LANG` | `Docstate`、`en` | 内置 `zh-CN` |
| `DOCSTATE_MCP` | `false` | 在站点进程里同时挂 MCP 端点 |

完整参考：[docs/configuration.md](docs/configuration.md)。`docstate check` 打印解析后的配置并探测存储。

## 部署

一个容器，一个数据库。[Docker Compose](docs/deployment/docker.md)（SQLite 或 PostgreSQL）、[Kubernetes](docs/deployment/kubernetes.md)（`deploy/kubernetes` 下的 kustomize base）。前面放登录代理，设 `DOCSTATE_AUTH_MODE=header`。

## 架构一段话

不依赖任何框架的**核心**（模型、发布规则、渲染、导入规则）背后是两个**存储端口**——文档与状态分开，因为它们的部署方式不同——由 SQL 适配器（SQLAlchemy + Alembic：SQLite、PostgreSQL、MySQL）和内存适配器实现；新后端通过 entry point 接入，通过同一套契约测试即合格。**身份**也是端口（`none` / `fake` / `header`，权限走 hook）。**服务端**是一层薄薄的 Starlette；**MCP 服务器**是独立的包，只和 HTTP API 说话。细节与图见 [docs/architecture.md](docs/architecture.md)。

## 路线图

- 静态构建（`docstate build`）上 GitHub Pages / Cloudflare Pages，状态后端用 Cloudflare Pages Function。
- OIDC 登录模式；基于规则的权限。
- 合并即发布的 GitHub Action；仓库资源（图片）。

## 许可证

MIT。Docstate 源自一个内部文档站，首个公开版本是对它的脱敏重构。
