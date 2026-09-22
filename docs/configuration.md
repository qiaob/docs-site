# 配置参考

一切可配置项都是环境变量，前缀 `DOCSTATE_`。也可以写在 `docstate.toml`（路径由 `DOCSTATE_CONFIG` 指定，默认当前目录的 `docstate.toml`）里，键名与环境变量相同、小写、去前缀，并支持 `[profiles.<name>]` 覆盖层，用 `DOCSTATE_PROFILE` 选择：

```toml
site_title = "Team docs"
lang = "zh-CN"
storage_url = "sqlite:///data/docstate.db"

[profiles.staging]
base_url = "https://docs.staging.example.com"
auth_mode = "header"

[profiles.prod]
base_url = "https://docs.example.com"
auth_mode = "header"
auth_header = "Cf-Access-Authenticated-User-Email"
```

优先级：环境变量 > `.env` 文件 > 选中的 profile > 文件顶层 > 代码默认值。**密钥只放环境变量**。`docstate check` 打印解析结果（隐去密钥）。

## 存储

| 变量 | 默认 | 说明 |
|---|---|---|
| `DOCSTATE_STORAGE_URL` | `sqlite:///data/docstate.db` | SQLAlchemy URL：`sqlite:///相对路径`、`sqlite:////绝对路径`、`postgresql://u:p@h/db`（自动用 psycopg 3）、`mysql://u:p@h/db`（PyMySQL，装 `docstate[mysql]`）、`memory://` |
| `DOCSTATE_STATE_URL` | 空 = 同上 | 文档状态放到另一个数据库 |
| `DOCSTATE_DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | 空 | 给了 HOST 就按分量拼 PostgreSQL URL，方便对接密钥管理 |
| `DOCSTATE_DB_TABLE_PREFIX` | 空 | 表名前缀，如 `docstate_`（与他人共库） |
| `DOCSTATE_DB_SCHEMA` | 空 | PostgreSQL 独立 schema，启动时 `CREATE SCHEMA IF NOT EXISTS`；SQLite 忽略 |
| `DOCSTATE_AUTO_MIGRATE` | `true` | 启动时跑 Alembic 迁移；关掉则手动 `docstate migrate` |

## 站点

| 变量 | 默认 | 说明 |
|---|---|---|
| `DOCSTATE_SITE_TITLE` | `Docstate` | 顶栏与页面标题 |
| `DOCSTATE_LANG` | `en` | 界面语言：`en`、`zh-CN` |
| `DOCSTATE_HOST` / `DOCSTATE_PORT` | `0.0.0.0` / `8787` | 监听地址 |
| `DOCSTATE_BASE_URL` | `http://localhost:8787` | 拼给发布者的 URL |
| `DOCSTATE_SOURCE_REPO_URL` | 空 | 文档里指向仓库内非文档文件的相对链接改写到这里，如 `https://github.com/org/docs/blob/main` |
| `DOCSTATE_TZ` | `UTC` | 页面显示时区 |
| `DOCSTATE_LOG_LEVEL` | `INFO` | |

## 读者身份

| 变量 | 默认 | 说明 |
|---|---|---|
| `DOCSTATE_AUTH_MODE` | `fake` | `none` 匿名读者（每个浏览器一个随机 id）；`fake` 演示身份，顶栏切换，**只用于本地**；`header` 信任登录代理写入的邮箱头 |
| `DOCSTATE_AUTH_HEADER` | `X-Forwarded-Email` | header 模式读哪个头。Cloudflare Access：`Cf-Access-Authenticated-User-Email`；oauth2-proxy：`X-Forwarded-Email` |
| `DOCSTATE_AUTH_PROXY_SECRET` / `DOCSTATE_AUTH_SECRET_HEADER` | 空 / `X-Docstate-Proxy-Secret` | 可选：代理再带一个共享密钥头，证明请求确实经过它（防止绕过代理直连 pod） |
| `DOCSTATE_ALLOWED_DOMAINS` | 空 = 任意 | 允许的邮箱域，逗号分隔 |
| `DOCSTATE_DEMO_VIEWERS` | `alice@…,bob@…,carol@example.com` | fake 模式的演示身份 |
| `DOCSTATE_LOGIN_URL` / `DOCSTATE_LOGOUT_URL` | 空 | 401 页面的登录入口；顶栏的退出链接 |
| `DOCSTATE_AUTHORIZER` | 空 = 全员可读可发 | `docstate.authorizer` entry point 名，见 [扩展 · 身份与权限](extending/auth.md) |

## 受信服务

| 变量 | 默认 | 说明 |
|---|---|---|
| `DOCSTATE_API_TOKENS` | 空 | `name:token,name2:token2`，或一个裸 token（名为 `api`）。带对 token 的调用方是受信服务，作者取它转发的作者头，否则用 token 名。不配置时只有 fake 模式算受信 |
| `DOCSTATE_API_TOKEN_HEADER` | `X-Docstate-Token` | 也接受 `Authorization: Bearer <token>` |
| `DOCSTATE_AUTHOR_HEADER` | `X-Docstate-Author` | 受信服务转发的作者邮箱 |

## 限制

| 变量 | 默认 |
|---|---|
| `DOCSTATE_MAX_DOC_BYTES` | 5 MiB |
| `DOCSTATE_MAX_STATE_BYTES` | 64 KiB |

## MCP（进程内挂载）

| 变量 | 默认 | 说明 |
|---|---|---|
| `DOCSTATE_MCP` | `false` | 在站点进程里把 MCP 端点挂到 `/mcp`（需要装 `docstate-mcp`）。独立进程见 [MCP 服务器](mcp.md) |
| `DOCSTATE_MCP_AUTHOR` | `mcp@localhost` | 没有 token 时进程内 MCP 的作者 |
| `DOCSTATE_MCP_SOURCE_ROOT` | 空 = 关 | `path=` 发布只允许读这个目录下的文件 |

## GitHub 回写（可选）

| 变量 | 默认 | 说明 |
|---|---|---|
| `DOCSTATE_GITHUB_REPO` | 空 = 关 | `owner/name` |
| `DOCSTATE_GITHUB_BRANCH` | `main` | |
| `DOCSTATE_GITHUB_TOKEN` | 空 | PAT；或用下面的 App |
| `DOCSTATE_GITHUB_APP_ID` / `DOCSTATE_GITHUB_APP_PRIVATE_KEY` | 空 | GitHub App（需要 `docstate[github]`），安装 token 只限该仓库 |
| `DOCSTATE_REPO_SYNC_MODE` | `direct` | `direct` 本站直接提交并开 PR；`dispatch` 只触发仓库工作流，由它拉 `/api/repo-sync/pending` 来写 |
| `DOCSTATE_GITHUB_DISPATCH_WORKFLOW` | `sync-from-docstate.yml` | dispatch 模式触发的工作流 |
| `DOCSTATE_REPO_SYNC_SKIP_CATEGORIES` | 空 | 不回写的一级分类 |
| `DOCSTATE_REPO_SYNC_MAX_DOCS` | `50` | 每次运行最多处理多少篇 |
