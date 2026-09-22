# Docstate 文档

| | |
|---|---|
| [快速上手](getting-started.md) | 安装、发布第一篇、写一篇带状态的 HTML |
| [概念](concepts.md) | 文档 / 版本 / 分类 / 状态作用域 / 沙箱 |
| [架构](architecture.md) | 核心 + 端口/适配器，请求时序，目录结构 |
| [配置参考](configuration.md) | 全部环境变量、`docstate.toml` 与 profile |
| [MCP 服务器](mcp.md) | 让 Claude Code / Cursor 等 agent 发布与读取文档 |
| [部署 · Docker](deployment/docker.md) · [Kubernetes](deployment/kubernetes.md) | 单容器 + SQLite / PostgreSQL |
| [协议 · State API](protocol/state-api.md) · [docbridge](protocol/docbridge.md) · [HTTP API](protocol/http-api.md) | 站点、壳页、文档、外部后端之间的约定 |
| [扩展 · 存储后端](extending/storage-backend.md) · [身份与权限](extending/auth.md) | 加一个数据库 / 接自己的登录与授权 |
| [写作 · Markdown](writing/markdown.md) · [HTML 与 DocState](writing/html-docstate.md) | 作者视角：能用什么、怎么存状态 |
| [安全模型](security.md) | 威胁模型、CSP、CSRF、静态托管下的退化 |
| [设计决策](design/) | ADR：为什么这样设计 |

文档以中文为主；README 提供英文版。术语在代码和 API 里保持英文（`slug`、`scope`、`me` / `shared`）。
