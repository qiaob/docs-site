# Changelog

## Unreleased

### Added
- First public version, extracted from an internal documentation site.
- Core / storage / auth / server layering; `DocumentStore` and `StateStore` ports.
- SQL storage (SQLite, PostgreSQL, MySQL) with Alembic migrations; in-memory storage; storage contract tests.
- Identity modes `none`, `fake`, `header` (with optional proxy secret); named API tokens; authorizer hook.
- `docstate` CLI: `serve`, `publish`, `import`, `migrate`, `check`.
- `docstate-mcp`: standalone MCP server over the HTTP API; tools, resources, in-process mount.
- `/api/search`; UI in English and Simplified Chinese; `docstate.toml` with profiles.
- Documentation: architecture, configuration, protocols, MCP, deployment, extension guides, security model.
