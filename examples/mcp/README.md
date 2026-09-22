# MCP 客户端配置片段

站点侧先发一个 token：`DOCSTATE_API_TOKENS=agent:<随机串>`。本地 `fake` 模式的站点不需要 token。

## Claude Code

```bash
claude mcp add docstate -e DOCSTATE_URL=https://docs.example.com -e DOCSTATE_TOKEN=<token> -e DOCSTATE_AUTHOR=you@example.com -- uvx docstate-mcp
```

## Claude Desktop / Cursor / Windsurf

`claude_desktop_config.json` / `.cursor/mcp.json`：见 [`mcp.json`](mcp.json)。

## Codex CLI

`~/.codex/config.toml`：

```toml
[mcp_servers.docstate]
command = "uvx"
args = ["docstate-mcp"]
env = { DOCSTATE_URL = "https://docs.example.com", DOCSTATE_TOKEN = "<token>" }
```

## 远程（HTTP 传输）

```bash
docstate-mcp --transport http --host 0.0.0.0 --port 9000 --source-root /srv/docs
```

放在你自己的鉴权代理后面；`--source-root` 限制 `path=` 能读的目录。
