"""The MCP surface. Tools map one-to-one onto the Docstate HTTP API; resources
expose document content as `docs://{slug}`.

    from docstate_mcp.client import DocstateClient
    from docstate_mcp.server import build_server
    mcp = build_server(DocstateClient("https://docs.example.com", token="..."))
    mcp.run(transport="stdio")
"""

from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP

from .client import DocstateClient

INSTRUCTIONS = (
    "Publish and read documents on a Docstate site. Use docs_publish to publish a "
    "Markdown or self-contained HTML document and get a stable URL; publishing again "
    "with the same slug adds a version at the same URL, identical content is reported as "
    "unchanged. Categories are directory-like paths (e.g. guides/onboarding). Run "
    "docs_check first to see what the site would flag (broken links, blocked scripts). "
    "Interactive HTML can persist reader state through window.DocState; Markdown task "
    "lists persist automatically. Read a published document as the resource docs://<slug>."
)

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
WRITE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True}
DESTRUCTIVE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True}


def _kind_for(path: str, kind: str | None) -> str:
    if kind in ("md", "html"):
        return kind
    return "html" if path.lower().endswith((".html", ".htm")) else "md"


def build_server(
    client: DocstateClient, *, source_root: Path | None = None, name: str = "docstate"
) -> FastMCP:
    """`source_root` confines `path=` publishing to one directory; leave it
    None for a stdio server on your own machine, set it when the server is
    reachable over HTTP."""
    mcp = FastMCP(name, instructions=INSTRUCTIONS)

    def read_local(path: str) -> str:
        target = Path(path).expanduser()
        if source_root is not None:
            root = source_root.resolve()
            target = (
                (root / path.lstrip("/")).resolve()
                if not target.is_absolute()
                else target.resolve()
            )
            if root != target and root not in target.parents:
                raise ValueError(f"path must be inside {root}")
        else:
            target = target.resolve()
        if not target.is_file():
            raise ValueError(f"no such file: {path}")
        return target.read_text(encoding="utf-8")

    def _payload(title, category, kind, content, path, slug, tags, summary, label, status) -> dict:
        if content is None and path is None:
            raise ValueError("give either content or path")
        if content is None:
            content = read_local(path)
        return {
            "title": title,
            "category": category,
            "kind": _kind_for(path or "", kind),
            "content": content,
            "slug": slug,
            "tags": tags,
            "summary": summary,
            "label": label,
            "status": status,
            "source_path": path if path and source_root is not None else None,
        }

    @mcp.tool(annotations=WRITE)
    async def docs_publish(
        title: str,
        category: str,
        kind: str | None = None,
        content: str | None = None,
        path: str | None = None,
        slug: str | None = None,
        tags: list[str] | None = None,
        summary: str | None = None,
        label: str | None = None,
        status: str | None = None,
    ) -> dict:
        """Publish a document and return its URL. Pass either `content` (the full
        Markdown/HTML text) or `path` (a local file). `kind` is "md" or "html"; when
        omitted it is inferred from the file extension (default md). Reusing an existing
        `slug` appends a new version at the same URL; identical content is reported as
        unchanged. `label` names the version (e.g. "v2: added June data"). `status` is
        draft | review | approved | deprecated. The result carries the site's warnings
        (broken links, scripts the sandbox will block)."""
        return await client.publish(
            _payload(title, category, kind, content, path, slug, tags, summary, label, status)
        )

    @mcp.tool(annotations=READ_ONLY)
    async def docs_check(
        content: str | None = None,
        path: str | None = None,
        kind: str | None = None,
        category: str = "misc",
    ) -> dict:
        """Run the pre-publish checks without publishing: relative links that will 404,
        images the site cannot serve, external scripts/styles the sandbox CSP blocks,
        [[wikilinks]] with no target. Returns {"warnings": [...]}."""
        result = await client.check(
            _payload("check", category, kind, content, path, None, None, None, None, None)
        )
        return {"warnings": result.get("warnings", [])}

    @mcp.tool(annotations=READ_ONLY)
    async def docs_list(
        category: str | None = None,
        tag: str | None = None,
        q: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List published documents, newest first. `category` matches the path and
        everything below it (e.g. "guides" covers guides/onboarding). `q` matches
        title, summary and tags."""
        return await client.list(
            category=category, tag=tag, q=q, status=status, limit=min(limit, 200)
        )

    @mcp.tool(annotations=READ_ONLY)
    async def docs_search(q: str, limit: int = 20) -> list[dict]:
        """Full-text search over titles, summaries, tags and document text. Each hit
        carries a `snippet` around the first match."""
        return await client.search(q, limit=min(limit, 100))

    @mcp.tool(annotations=READ_ONLY)
    async def docs_get(
        slug: str, version: int | None = None, include_content: bool = False
    ) -> dict:
        """A document's metadata (and optionally its content) at the latest or a given version."""
        return await client.get(slug, version=version, include_content=include_content)

    @mcp.tool(annotations=READ_ONLY)
    async def docs_versions(slug: str) -> list[dict]:
        """Version history of one document, newest first."""
        return await client.versions(slug)

    @mcp.tool(annotations=READ_ONLY)
    async def docs_categories() -> list[dict]:
        """The category tree with document counts."""
        return await client.categories()

    @mcp.tool(annotations=WRITE)
    async def docs_update_meta(
        slug: str,
        title: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        summary: str | None = None,
        status: str | None = None,
    ) -> dict:
        """Change title / category / tags / summary / status without creating a version."""
        fields = {
            k: v
            for k, v in dict(
                title=title, category=category, tags=tags, summary=summary, status=status
            ).items()
            if v is not None
        }
        return await client.update_meta(slug, **fields)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def docs_archive(slug: str) -> dict:
        """Archive a document: it leaves lists and search, its URL keeps answering.
        Publishing to the slug again restores it."""
        return await client.archive(slug)

    @mcp.resource("docs://{slug}", mime_type="text/plain")
    async def document(slug: str) -> str:
        """The latest content of a published document."""
        doc = await client.get(slug, include_content=True)
        return doc["version"]["content"]

    @mcp.resource("docs://{slug}/v/{version}", mime_type="text/plain")
    async def document_version(slug: str, version: str) -> str:
        """The content of one version of a published document."""
        doc = await client.get(slug, version=int(version), include_content=True)
        return doc["version"]["content"]

    return mcp
