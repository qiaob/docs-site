# docstate-mcp

MCP server for [Docstate](https://github.com/qiaob/docs-site): lets an AI agent
publish, check, search and read documents on any Docstate site.

```bash
claude mcp add docstate -e DOCSTATE_URL=https://docs.example.com -e DOCSTATE_TOKEN=... -- uvx docstate-mcp
```

Tools: `docs_publish`, `docs_check`, `docs_list`, `docs_search`, `docs_get`,
`docs_versions`, `docs_categories`, `docs_update_meta`, `docs_archive`.
Resources: `docs://{slug}`, `docs://{slug}/v/{n}`.

See [docs/mcp.md](https://github.com/qiaob/docs-site/blob/main/docs/mcp.md).
