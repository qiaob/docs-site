# Contributing

Thanks for looking. A few things that keep the project easy to work on:

## Setup

```bash
git clone https://github.com/qiaob/docs-site && cd docstate
uv sync                      # both packages, editable, plus dev tools
uv run docstate serve        # http://localhost:8787
uv run pytest -q
```

Or entirely in Docker: `make up`, `make test`, `make lint`, `make fmt`. `make test-pg`
runs the storage contract tests against PostgreSQL as well.

## Layout

A uv workspace with two packages: `packages/docstate` (the site) and
`packages/docstate-mcp` (the MCP server, which only talks to the site's HTTP
API). Read [docs/architecture.md](docs/architecture.md) first; the short
version is: rules live in `docstate.core`, storage adapters are thin, the server
is thinner.

## Rules of thumb

- **Core stays framework-free.** Nothing under `docstate/core` imports Starlette,
  SQLAlchemy or Jinja for the shell (the Markdown wrapper is the one template it owns).
- **Storage adapters pass the contract.** `tests/storage/test_contract.py` is the
  definition of correct; add your backend to `BACKENDS` and make it green.
- **Every entry point calls the same use cases.** HTTP, CLI, MCP and import all
  go through `docstate.core.publish`; do not reimplement "what counts as a new
  version" anywhere else.
- **Configuration is environment variables.** New options go into `settings.py`
  with a comment, and into `docs/configuration.md`.
- **UI strings go through `i18n.py`** in both `en` and `zh-CN`.
- **Security boundaries are documented in `docs/security.md`**; a change to the
  CSP, the bridge protocol or the state API needs a matching doc change.

## Before you open a pull request

```bash
make lint && make test
```

Commit messages follow Conventional Commits (`feat(server): …`, `fix(storage): …`).
Add a line to `CHANGELOG.md` under *Unreleased*.
