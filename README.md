# Docstate

**Publish Markdown and interactive HTML as versioned documents that remember state. Self-hosted, and one MCP call away for AI agents.**

[中文说明](README.zh-CN.md) · [Documentation](docs/README.md) · [MCP server](docs/mcp.md) · [Architecture](docs/architecture.md)

Docstate is a small document site with one idea at its centre: a document can be
a Markdown file *or* a self-contained HTML page — a chart, a checklist, a
dashboard an AI wrote for you — and either one gets a stable URL, a version
history, a place in the category tree, and **state**: checkboxes, notes and
selections that persist per reader or for the whole team, without the author
writing a backend.

```text
   Markdown / HTML  ──►  /d/<slug>   stable URL, versions at the same address
                         sandboxed:  the document runs in an isolated iframe
                         stateful:   window.DocState.get / set, per reader or shared
                         organised:  directory-like categories, timeline, search
                         agent-ready: MCP tools publish and read; git can be the source
```

## Why

| You want to… | What usually happens | Docstate |
|---|---|---|
| share an interactive HTML report with the team | paste it in a chat, or host it somewhere with no versions, no index | it is a document like any other, with a URL, versions and a category |
| let an AI agent publish what it produced | copy-paste | `docs_publish` returns the URL; a dry run tells the agent what would break |
| keep a checklist inside a document | it resets on every reload | `DocState.set("checklist", …)` persists per reader or shared |
| stay in control | a SaaS holds your documents | one container, SQLite or PostgreSQL, your login proxy in front |

Documents run inside a CSP-`sandbox`ed iframe with an opaque origin: a document
cannot read the reader's cookies or call the site's API. Everything it needs
goes through a small `postMessage` protocol to the shell page, which holds the
session. That is what makes "anyone (including a model) may publish HTML with
scripts" safe.

## Quick start

```bash
pip install "docstate[postgres]"     # or: uv tool install docstate
docstate serve                       # http://localhost:8787, SQLite in ./data
docstate import ./docs               # publish a directory of .md / .html files
```

Or with Docker:

```bash
git clone https://github.com/qiaob/docs-site && cd docstate
make up && make import               # the site with the example documents
```

Open http://localhost:8787. The top bar lets you switch between demo readers
(`fake` auth mode) so you can see per-reader state at work; look at
`/d/docstate-demo` and `/d/interactive-lab`.

## Publish

```bash
# a file, through the HTTP API
docstate publish report.html --category analytics/reports --label "June data"
# the API directly
curl -s localhost:8787/api/publish -H 'Content-Type: application/json' \
  -d '{"title":"Hello","kind":"md","category":"guides","slug":"hello","content":"# Hello"}'
```

Publishing to the same slug again adds a version; identical content is reported
as `unchanged`. `dry_run: true` returns only the warnings (relative links that
would 404, scripts the sandbox blocks, `[[wikilinks]]` with no target).

### From an AI agent (MCP)

```bash
claude mcp add docstate -e DOCSTATE_URL=https://docs.example.com -e DOCSTATE_TOKEN=… -- uvx docstate-mcp
```

The [`docstate-mcp`](packages/docstate-mcp) server runs next to the agent and
talks to the site's HTTP API. Tools: `docs_publish`, `docs_check`, `docs_list`,
`docs_search`, `docs_get`, `docs_versions`, `docs_categories`,
`docs_update_meta`, `docs_archive`; resources `docs://{slug}`. See
[docs/mcp.md](docs/mcp.md).

## State inside a document

```js
await DocState.get("checklist", { scope: "me" });                 // per reader, across devices
await DocState.set("checklist", { 0: true }, { scope: "me" });
await DocState.set("note", { text: "..." }, { scope: "shared" }); // one value for everyone
DocState.subscribe("note", v => render(v), { scope: "shared" });  // poll for others' changes
```

Markdown needs no code: task-list checkboxes (`- [ ]`) save automatically, per
reader by default, for everyone with `task_scope: shared` in the frontmatter.

## Configuration

Everything is an environment variable with the `DOCSTATE_` prefix; an optional
`docstate.toml` holds the non-secret ones and per-environment profiles. The
important ones:

| Variable | Default | |
|---|---|---|
| `DOCSTATE_STORAGE_URL` | `sqlite:///data/docstate.db` | `postgresql://…`, `mysql://…`, `memory://` |
| `DOCSTATE_STATE_URL` | same as storage | put document state in another database |
| `DOCSTATE_AUTH_MODE` | `fake` | `none` (public), `fake` (dev), `header` (behind a login proxy) |
| `DOCSTATE_API_TOKENS` | | `ci:…,agent:…` — trusted callers for the API and MCP |
| `DOCSTATE_SITE_TITLE`, `DOCSTATE_LANG` | `Docstate`, `en` | `zh-CN` is built in |
| `DOCSTATE_MCP` | `false` | also mount the MCP endpoint in the site process |

Full reference: [docs/configuration.md](docs/configuration.md). `docstate check`
prints the resolved configuration and probes the storage.

## Deploy

One container, one database. [Docker Compose](docs/deployment/docker.md) (SQLite
or PostgreSQL), [Kubernetes](docs/deployment/kubernetes.md) (kustomize base
under `deploy/kubernetes`). Put your login proxy in front and set
`DOCSTATE_AUTH_MODE=header`.

## Architecture in one paragraph

A framework-free **core** (models, publishing rules, rendering, import rules)
sits behind two **storage ports** — documents and state, separate because they
deploy differently — implemented by a SQL adapter (SQLAlchemy + Alembic:
SQLite, PostgreSQL, MySQL) and an in-memory one; new backends plug in through
an entry point and must pass one contract test suite. **Identity** is a port
too (`none` / `fake` / `header`, permissions via a hook). The **server** is a
thin Starlette app; the **MCP server** is a separate package that only speaks
the HTTP API. Details and diagrams: [docs/architecture.md](docs/architecture.md).

## Roadmap

- Static build (`docstate build`) for GitHub Pages / Cloudflare Pages, with a
  Cloudflare Pages Function as the state backend.
- OIDC login mode; rule-based permissions.
- GitHub Action for publishing on merge; repository assets (images).

## License

MIT. Docstate grew out of an internal documentation site; the first public
version is a clean-room extraction of it.
