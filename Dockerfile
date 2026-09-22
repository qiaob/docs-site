# One image, two targets: `test` (with dev tooling) and `runtime`. uv installs the
# workspace (docstate + docstate-mcp) from the lockfile; nothing is resolved at
# build time.
FROM python:3.11-slim AS base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/docstate/pyproject.toml packages/docstate/README.md packages/docstate/
COPY packages/docstate-mcp/pyproject.toml packages/docstate-mcp/README.md packages/docstate-mcp/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-workspace --no-dev
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

FROM base AS test
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen
CMD ["uv", "run", "pytest", "-q"]

FROM base AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    DOCSTATE_HOST=0.0.0.0 \
    DOCSTATE_PORT=8787 \
    DOCSTATE_STORAGE_URL=sqlite:////data/docstate.db
RUN useradd --system --uid 10001 --home /app docstate \
    && mkdir -p /data \
    && chown -R docstate /data /app
USER docstate
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=2).status == 200 else 1)"
CMD ["docstate", "serve"]
