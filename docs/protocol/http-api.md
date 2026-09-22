# HTTP API

所有 JSON 接口在 `/api/` 下；401/403 对 `/api/` 返回 JSON，对页面返回提示页。

## 身份

| 调用方 | 怎么表明 |
|---|---|
| 读者（浏览器） | 会话：`fake` 模式的 cookie、`header` 模式的代理头、`none` 模式的匿名 id |
| 受信服务 | `X-Docstate-Token: <token>` 或 `Authorization: Bearer <token>`，可选 `X-Docstate-Author: who@example.com` 指明作者 |

## 文档

| 方法 · 路径 | 说明 |
|---|---|
| `POST /api/publish` | 发布。body：`title, kind (md\|html), category, content, slug?, tags?, summary?, label?, status?, source_path?, dry_run?, author?`。返回 `{outcome, url, slug, version, title, category, warnings}`；`dry_run` 时 `{outcome: "dry_run", warnings}` |
| `GET /api/docs?category=&tag=&q=&status=&limit=` | 列表（在线文档，最新在前） |
| `GET /api/search?q=&limit=` | 全文搜索，每条带 `snippet` |
| `GET /api/categories` | 分类树 `[{path, name, count, children}]` |
| `GET /api/docs/{slug}?version=&content=1` | 一篇文档，可带某版本正文 |
| `GET /api/docs/{slug}/versions` | 版本列表 |
| `PATCH /api/docs/{slug}` | 改 `title / category / tags / summary / status`，不产生版本（需要 `publish` 权限或受信 token） |
| `POST /api/docs/{slug}/archive` | 归档（需要 `admin` 权限或受信 token） |

文档对象：

```json
{
  "slug": "hello", "url": "https://docs.example.com/d/hello",
  "title": "Hello", "category": "guides", "tags": ["a"], "summary": "…",
  "status": "draft", "kind": "md", "latest_version": 2,
  "created_by": "alice@example.com", "created_at": "…Z", "updated_at": "…Z", "archived_at": null,
  "repo": {"path": "guides/hello.md", "state": "synced", "synced_version": 2, "pr_url": null, "error": null, "updated_at": "…Z"},
  "version": {"no": 2, "label": "v2", "size_bytes": 120, "created_by": "…", "created_at": "…Z", "source_path": null, "url": "…/d/hello?v=2", "content": "…"}
}
```

## 状态

见 [State API](state-api.md)。

## 导入（受信服务）

`POST /api/import`：

```json
{"ref": "<commit>", "label": "<commit subject>",
 "files": [{"path": "guides/x.md", "content": "...", "author": "a@b", "committed_at": "2026-09-10T02:00:00Z", "deleted": false}]}
```

同一路径对应同一篇文档；内容没变 `unchanged`；`deleted: true` 归档；不在可发布集合内的路径（`.git/`、`templates/`、`CLAUDE.md` 等）跳过。返回 `{ref, counts, results}`。

## 回写（受信服务）

`GET /api/repo-sync/pending`：dispatch 模式下，仓库自己的工作流拉取要写的文件计划 `{base, files: [{path, action, content, message, author, slug, title}]}`。

## 健康检查

`GET /healthz` → `ok`（探测存储连通）。
