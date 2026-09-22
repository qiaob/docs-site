# 部署：Docker

## 单容器 + SQLite

最省事的形态：一个容器、一个持久卷。

```yaml
# docker-compose.yml
services:
  docstate:
    image: ghcr.io/qiaob/docs-site:latest
    ports: ["8787:8787"]
    environment:
      DOCSTATE_STORAGE_URL: sqlite:////data/docstate.db
      DOCSTATE_BASE_URL: https://docs.example.com
      DOCSTATE_AUTH_MODE: header
      DOCSTATE_AUTH_HEADER: Cf-Access-Authenticated-User-Email
      DOCSTATE_API_TOKENS: agent:${AGENT_TOKEN}
      DOCSTATE_SITE_TITLE: Team docs
      DOCSTATE_LANG: zh-CN
    volumes:
      - docstate-data:/data
volumes:
  docstate-data:
```

SQLite 只适合单副本；写入量不大的团队文档站完全够用。

## 单容器 + PostgreSQL

```yaml
services:
  docstate:
    image: ghcr.io/qiaob/docs-site:latest
    ports: ["8787:8787"]
    environment:
      DOCSTATE_STORAGE_URL: postgresql://docstate:${DB_PASSWORD}@db:5432/docstate
      DOCSTATE_BASE_URL: https://docs.example.com
      DOCSTATE_AUTH_MODE: header
    depends_on: [db]
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: docstate
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: docstate
    volumes:
      - pgdata:/var/lib/postgresql/data
volumes:
  pgdata:
```

完整文件在 `deploy/docker-compose.postgres.yml`。PostgreSQL 下可以跑多副本；迁移默认在启动时自动执行，多副本同时启动时 Alembic 的版本表会串行化，也可以关掉 `DOCSTATE_AUTO_MIGRATE` 改为部署前手动 `docstate migrate`。

## 登录代理

站点自己不做登录。把它放在 Cloudflare Access、oauth2-proxy、Tailscale Serve 或你的网关后面，设 `DOCSTATE_AUTH_MODE=header` 与对应的头名。如果容器可能被绕过代理直连，再配 `DOCSTATE_AUTH_PROXY_SECRET`。

## 镜像

`Dockerfile` 的 `runtime` 目标：非 root 用户 `docstate`（uid 10001）、`/data` 卷、`/healthz` 健康检查、入口 `docstate serve`。镜像里同时装了 `docstate-mcp`，所以 `DOCSTATE_MCP=true` 就能在进程内挂 MCP 端点。

```bash
docker build --target runtime -t docstate .
```

## 备份

SQLite：备份 `/data/docstate.db`（WAL 模式，用 `sqlite3 .backup` 或先停容器）。PostgreSQL：常规 `pg_dump`。所有文档正文都在 `doc_versions` 表里。
