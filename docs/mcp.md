# MCP 服务器

`docstate-mcp` 是一个独立的包和进程，让 MCP 客户端（Claude Code、Claude Desktop、Cursor、Codex CLI……）对着任何一个 Docstate 站点发布与读取文档。它**只依赖站点的 HTTP API**：装在 agent 那一侧，不需要数据库访问，站点也不用开额外端口。

```
Claude Code ──stdio──► docstate-mcp（本机进程）──HTTPS + token──► 站点 /api/*
                       path= 读的是本机文件
```

## 安装与接入

```bash
# Claude Code
claude mcp add docstate -e DOCSTATE_URL=https://docs.example.com -e DOCSTATE_TOKEN=<token> -- uvx docstate-mcp
```

Claude Desktop / Cursor（`mcp.json`）：

```json
{
  "mcpServers": {
    "docstate": {
      "command": "uvx",
      "args": ["docstate-mcp"],
      "env": {
        "DOCSTATE_URL": "https://docs.example.com",
        "DOCSTATE_TOKEN": "<token>",
        "DOCSTATE_AUTHOR": "you@example.com"
      }
    }
  }
}
```

更多片段在 `examples/mcp/`。

## 配置

| 变量 / 参数 | 说明 |
|---|---|
| `DOCSTATE_URL` / `--url` | 站点地址，默认 `http://localhost:8787` |
| `DOCSTATE_TOKEN` / `--token` | 站点侧配置的命名 token（`DOCSTATE_API_TOKENS`）。本地 fake 模式的站点不需要 |
| `DOCSTATE_AUTHOR` / `--author` | 发布时记录的作者邮箱；不给则用 token 的名字 |
| `--transport stdio|http` | 默认 stdio。`http` 给远程 agent 用，请放在你自己的鉴权代理后面 |
| `--host` / `--port` | http 传输的监听地址，默认 `127.0.0.1:9000` |
| `DOCSTATE_MCP_SOURCE_ROOT` / `--source-root` | 把 `path=` 发布限制在这个目录下；http 传输时务必设置 |

## 工具

| 工具 | 说明 |
|---|---|
| `docs_publish(title, category, kind?, content \| path, slug?, tags?, summary?, label?, status?)` | 发布或追加版本。`path` 是本机文件，kind 不给时按扩展名推断。返回 `outcome`、`url`、`version`、`warnings` |
| `docs_check(content \| path, kind?)` | 只跑发布前检查：会 404 的相对链接、站点提供不了的图片、沙箱会拦的外链脚本/样式、找不到目标的 `[[wikilink]]` |
| `docs_list(category?, tag?, q?, status?, limit?)` | 列表，最新在前；`category` 含子目录 |
| `docs_search(q, limit?)` | 全文搜索，每条带 `snippet` |
| `docs_get(slug, version?, include_content?)` | 元信息，可带正文 |
| `docs_versions(slug)` | 版本历史 |
| `docs_categories()` | 分类树 |
| `docs_update_meta(slug, title?, category?, tags?, summary?, status?)` | 改元信息，不产生版本 |
| `docs_archive(slug)` | 归档（`destructiveHint`）；再发布到同一 slug 会恢复 |

资源：`docs://{slug}`（最新正文）、`docs://{slug}/v/{n}`。agent 引用一篇已发布文档时可以直接读资源。

所有工具都带 `readOnlyHint / destructiveHint / idempotentHint` 注解，客户端据此决定是否要确认。

## 给 agent 的提示词建议

把这段放进项目的 `CLAUDE.md` / `AGENTS.md`：

> 生成的报告、看板、检查清单用 docstate 的 `docs_publish` 发布到 `<分类>`，先用 `docs_check` 看警告；HTML 要自包含，外链脚本只用 cdnjs 或 jsdelivr；需要记住读者操作的地方用 `window.DocState`（见 docs://writing-html-docstate）。发布后把 URL 回给我。

## 进程内挂载

单容器部署时可以让站点自己带 MCP 端点：`DOCSTATE_MCP=true`（或 `docstate serve --mcp`）把同一个 FastMCP 应用挂在 `/mcp`。工具通过内存里的 ASGI 传输调站点自己的 API，所以没有第二条代码路径。此时 MCP 端点本身没有鉴权，请放在登录代理后面，或只在本地用。

## 身份模型

首版是「命名 token + 配置作者」：站点给 agent 发一个 token（`DOCSTATE_API_TOKENS=agent:…`），MCP 服务器带着它调用，作者是 `DOCSTATE_AUTHOR` 或 token 名。按人授权的 OAuth（MCP 规范）列在路线图。
