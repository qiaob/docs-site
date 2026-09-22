"""Publishing use cases, written against the DocumentStore port.

This is the one place that knows what "publishing" means: when a document is
created versus given a new version, when content counts as unchanged, how a
slug is chosen, how the sidebar tree and the timeline are shaped. Every entry
point — HTTP API, CLI, MCP, repository import — calls these functions; storage
adapters only read and write."""

from __future__ import annotations

from dataclasses import replace
from zoneinfo import ZoneInfo

from docstate.core import text
from docstate.core.clock import iso_utc, to_local, utcnow
from docstate.core.models import (
    KINDS,
    STATUSES,
    DocQuery,
    Document,
    PublishRequest,
    PublishResult,
    RepoBinding,
    SearchHit,
    Version,
)
from docstate.core.render import extract_text
from docstate.storage.base import DocumentStore


def unique_slug(store: DocumentStore, base: str) -> str:
    slug, n = base, 2
    while store.slug_exists(slug):
        slug = f"{base}-{n}"
        n += 1
    return slug


def publish(store: DocumentStore, req: PublishRequest) -> PublishResult:
    """Create a document or append a version. The outcome is `created`,
    `new_version` or `unchanged`; unchanged means the latest version already
    has this content (ignoring frontmatter), and nothing is written."""
    kind = (req.kind or "").lower()
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if req.status and req.status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    now = req.created_at or utcnow()
    sha = text.content_sha(req.content)
    plain = extract_text(req.content, kind)
    title = (req.title or "").strip() or (req.slug or "untitled")

    with store.transaction():
        doc = store.get(req.slug) if req.slug else None
        if doc is None:
            doc = Document(
                slug=unique_slug(store, text.make_slug(title, req.slug, now)),
                title=title,
                category=text.normalize_category(req.category),
                kind=kind,
                created_by=req.author,
                created_at=now,
                updated_at=now,
                tags=[str(t) for t in (req.tags or [])],
                summary=req.summary or text.auto_summary(plain),
                status=req.status or "draft",
                latest_version=0,
            )
            store.create(doc)
            outcome = "created"
        else:
            last = store.get_version(doc.slug, None)
            if last is not None and (
                last.content_sha == sha
                or text.body_sha(last.content, kind) == text.body_sha(req.content, kind)
            ):
                return PublishResult(doc, last, "unchanged")
            doc = replace(
                doc,
                title=title,
                category=text.normalize_category(req.category) if req.category else doc.category,
                tags=[str(t) for t in req.tags] if req.tags is not None else doc.tags,
                summary=req.summary or doc.summary,
                status=req.status or doc.status,
                kind=kind,
                archived_at=None,
            )
            outcome = "new_version"

        version = Version(
            slug=doc.slug,
            version_no=doc.latest_version + 1,
            content=req.content,
            content_sha=sha,
            size_bytes=len(req.content.encode("utf-8")),
            created_by=req.author,
            created_at=now,
            label=req.label or "",
            text_plain=plain,
            source_path=req.source_path,
        )
        store.add_version(version)
        doc = replace(doc, latest_version=version.version_no, updated_at=now)
        store.update(doc)
    return PublishResult(doc, version, outcome)


def update_meta(store: DocumentStore, slug: str, **fields) -> Document:
    """Change title / category / tags / summary / status. No new version."""
    doc = store.get(slug)
    if doc is None:
        raise ValueError(f"no document with slug {slug!r}")
    changes: dict = {}
    for key, value in fields.items():
        if value is None:
            continue
        if key == "tags":
            changes["tags"] = [str(t) for t in value]
        elif key == "category":
            changes["category"] = text.normalize_category(value)
        elif key == "status":
            if value not in STATUSES:
                raise ValueError(f"status must be one of {STATUSES}")
            changes["status"] = value
        elif key in ("title", "summary"):
            changes[key] = value
    if not changes:
        return doc
    return store.update(replace(doc, **changes))


def archive(store: DocumentStore, slug: str) -> Document:
    """Soft delete: the document leaves lists and search, its URL keeps answering."""
    doc = store.get(slug)
    if doc is None:
        raise ValueError(f"no document with slug {slug!r}")
    if doc.archived_at is not None:
        return doc
    return store.update(replace(doc, archived_at=utcnow()))


def resolve_wikilink(store: DocumentStore, name: str) -> str | None:
    """`[[name]]` -> slug: exact slug, slugified name, exact title, then a slug
    ending in the slugified name (numbered file names: `[[tailscale]]` finds
    `001-tailscale`)."""
    name = (name or "").strip()
    if not name:
        return None
    if doc := store.get(name):
        return doc.slug
    cand = text.slugify(name)
    if cand and (doc := store.get(cand)):
        return doc.slug
    if doc := store.by_title(name):
        return doc.slug
    if cand and (doc := store.by_slug_suffix(cand)):
        return doc.slug
    return None


def readme_for(store: DocumentStore, category: str) -> Document | None:
    """A directory's README.md (the repository root's for the home page), if
    it is published and live — shown at the top of the category page."""
    path = "README.md" if category in ("", "general") else f"{category}/README.md"
    doc = store.by_source_path(path)
    return doc if doc is not None and not doc.is_archived else None


def category_tree(store: DocumentStore) -> list[dict]:
    """The sidebar's file tree: directories with their subtree counts and the
    live documents directly in each one (README first, then natural order of
    the file names, so numbered files keep the repository's order)."""
    root: dict[str, dict] = {}
    for row in store.tree_rows():
        children = root
        parts = row.category.split("/")
        node: dict = {}
        for i, part in enumerate(parts):
            node = children.setdefault(
                part,
                {
                    "name": part,
                    "path": "/".join(parts[: i + 1]),
                    "count": 0,
                    "children": {},
                    "docs": [],
                },
            )
            node["count"] += 1
            children = node["children"]
        file = (row.source_path or "").rsplit("/", 1)[-1]
        node["docs"].append(
            {
                "slug": row.slug,
                "title": row.title,
                "kind": row.kind,
                "file": file,
                "readme": file.lower() == "readme.md",
            }
        )

    def to_list(d: dict[str, dict]) -> list[dict]:
        out = []
        for n in sorted(d.values(), key=lambda n: n["name"]):
            n["docs"].sort(
                key=lambda x: (not x["readme"], text.natural_key(x["file"] or x["title"]))
            )
            out.append(dict(n, children=to_list(n["children"])))
        return out

    return to_list(root)


def timeline(
    store: DocumentStore, *, category: str | None = None, limit: int = 500, tz: ZoneInfo
) -> list[dict]:
    """Versions newest first, grouped by the local calendar day."""
    groups: list[dict] = []
    for entry in store.timeline(category, limit):
        local = to_local(entry.version.created_at, tz)
        day = local.date().isoformat() if local else ""
        if not groups or groups[-1]["day"] != day:
            groups.append({"day": day, "items": []})
        groups[-1]["items"].append({"version": entry.version, "doc": entry.doc})
    return groups


def search(store: DocumentStore, q: str, *, limit: int = 50) -> list[SearchHit]:
    q = (q or "").strip()
    if not q:
        return []
    return [SearchHit(doc, text.snippet(plain or "", q)) for doc, plain in store.search(q, limit)]


def list_docs(store: DocumentStore, **kw) -> list[Document]:
    return store.list(DocQuery(**kw))


# ------------------------------------------------------------------ payloads
def doc_payload(
    store: DocumentStore,
    doc: Document,
    version: Version | None = None,
    *,
    include_content: bool = False,
    base_url: str = "",
) -> dict:
    """The JSON shape of a document for the API and the MCP tools."""
    out = {
        "slug": doc.slug,
        "url": f"{base_url}/d/{doc.slug}",
        "title": doc.title,
        "category": doc.category,
        "tags": list(doc.tags),
        "summary": doc.summary,
        "status": doc.status,
        "kind": doc.kind,
        "latest_version": doc.latest_version,
        "created_by": doc.created_by,
        "created_at": iso_utc(doc.created_at),
        "updated_at": iso_utc(doc.updated_at),
        "archived_at": iso_utc(doc.archived_at),
        "repo": repo_payload(store.repo_binding(doc.slug), doc),
    }
    if version is not None:
        out["version"] = version_payload(doc, version, base_url=base_url)
        if include_content:
            out["version"]["content"] = version.content
    return out


def repo_payload(row: RepoBinding | None, doc: Document) -> dict | None:
    """Write-back state for the API: where the document is in git and whether
    what is there is current."""
    if row is None:
        return None
    if row.deleted_at:
        state = "deleted"
    elif row.pr_state == "open":
        state = "pending_review"
    elif row.last_error and row.synced_version is None:
        state = "error"
    else:
        state = "synced" if row.synced_version == doc.latest_version else "pending"
    return {
        "path": row.path,
        "state": state,
        "synced_version": row.synced_version,
        "pr_url": row.pr_url,
        "error": row.last_error,
        "updated_at": iso_utc(row.updated_at),
    }


def version_payload(doc: Document, version: Version, *, base_url: str = "") -> dict:
    return {
        "no": version.version_no,
        "label": version.label,
        "size_bytes": version.size_bytes,
        "created_by": version.created_by,
        "created_at": iso_utc(version.created_at),
        "source_path": version.source_path,
        "url": f"{base_url}/d/{doc.slug}?v={version.version_no}",
    }
