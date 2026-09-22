"""Turning repository files into documents.

Used by `docstate import` (a checkout on disk), the bulk import API (a GitHub
Action posting changed files after a merge) and the static builder. One file
= one document: the directory is the category, the file stem is the slug,
frontmatter supplies title / tags / status / dates, and the content hash
decides whether a new version is created."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from zoneinfo import ZoneInfo

import frontmatter

from docstate.core import publish as pub
from docstate.core import text
from docstate.core.clock import UTC, local_to_utc
from docstate.core.models import STATUSES, Document, PublishRequest, PublishResult
from docstate.core.render import html_description, html_title
from docstate.storage.base import DocumentStore

SKIP_DIRS = {
    ".git",
    ".obsidian",
    ".playwright-mcp",
    ".claude",
    ".github",
    "templates",
    "node_modules",
    "assets",
}
SKIP_PREFIXES = ("Untitled", "未命名")
# instructions for AI assistants, not documents for people
SKIP_NAMES = {"claude.md", "agents.md", "gemini.md", "copilot-instructions.md"}
MIN_BYTES = 30
_DATE_RE = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})")


@dataclass
class FileMeta:
    title: str
    tags: list[str] = field(default_factory=list)
    status: str = "approved"
    author: str = "repo"
    created: dt.datetime | None = None
    updated: dt.datetime | None = None
    summary: str = ""
    explicit: frozenset[str] = frozenset()  # keys the frontmatter actually set


def parse_date(value) -> dt.datetime | None:
    """Frontmatter dates (YAML date/datetime or string) -> naive local datetime."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day, 9, 0)
    m = _DATE_RE.match(str(value).strip())
    if m:
        try:
            return dt.datetime(int(m[1]), int(m[2]), int(m[3]), 9, 0)
        except ValueError:
            return None
    return None


def wanted(rel_path: str) -> bool:
    """Whether a repository path is a document we publish."""
    p = PurePosixPath(rel_path)
    if p.suffix.lower() not in (".md", ".html", ".htm"):
        return False
    if set(p.parts[:-1]) & SKIP_DIRS or p.name.lower() in SKIP_NAMES:
        return False
    return not p.name.startswith(SKIP_PREFIXES)


def kind_of(rel_path: str) -> str:
    return "md" if PurePosixPath(rel_path).suffix.lower() == ".md" else "html"


def category_of(rel_path: str) -> str:
    parent = "/".join(PurePosixPath(rel_path).parts[:-1])
    return parent or "general"


def md_meta(rel_path: str, source: str) -> FileMeta:
    try:
        post = frontmatter.loads(source)
        meta, body = dict(post.metadata), post.content
    except Exception:  # malformed YAML: treat the whole file as body
        meta, body = {}, source
    stem = PurePosixPath(rel_path).stem
    title = str(meta.get("title") or "").strip()
    if not title:
        m = re.search(r"^#\s+(.+?)\s*$", body, re.M)
        title = m.group(1).strip() if m else stem
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    status = str(meta.get("status")) if meta.get("status") in STATUSES else "approved"
    summary = ""
    # fenced blocks first: a mermaid diagram with blank lines inside would
    # otherwise contribute "subgraph ..." as the summary
    body_for_summary = re.sub(r"```.*?```|~~~.*?~~~", " ", body, flags=re.S)
    for para in re.split(r"\n\s*\n", body_for_summary):
        line = para.strip()
        if not line or line.startswith(
            ("#", "```", "~~~", "|", "<", "---", ">", "![", "- [", "* [")
        ):
            continue
        summary = text.auto_summary(re.sub(r"[`*_\[\]>#]", "", line).replace("\n", " "))
        break
    return FileMeta(
        title=title,
        tags=[str(t) for t in tags],
        status=status,
        author=str(meta.get("author") or "repo"),
        created=parse_date(meta.get("created")),
        updated=parse_date(meta.get("updated")),
        summary=summary,
        explicit=frozenset(str(k) for k in meta),
    )


def html_meta(rel_path: str, source: str) -> FileMeta:
    return FileMeta(
        title=html_title(source) or PurePosixPath(rel_path).stem,
        summary=html_description(source) or "",
    )


def preferred_slug(rel_path: str) -> str:
    p = PurePosixPath(rel_path)
    stem = p.stem.lower()
    if stem in text.GENERIC_STEMS or len(stem) < 6:
        parent = p.parent.name.lower() if p.parent.name else "root"
        return text.slugify(f"{parent}-{stem}")
    return text.slugify(stem)


def find_by_source(store: DocumentStore, rel_path: str) -> Document | None:
    """The document whose first version came from this repository path."""
    return store.by_source_path(rel_path)


def import_file(
    store: DocumentStore,
    rel_path: str,
    source: str,
    *,
    author: str | None = None,
    committed_at: dt.datetime | None = None,
    label: str | None = None,
    tz: ZoneInfo = UTC,
) -> PublishResult:
    """Publish one repository file. `author` / `committed_at` (naive UTC) come
    from git when the caller has them; frontmatter and the filename date are the
    fallbacks. Same path -> same document; a slug collision with a different
    path gets the parent-directory prefix."""
    kind = kind_of(rel_path)
    meta = md_meta(rel_path, source) if kind == "md" else html_meta(rel_path, source)
    when_local = meta.updated or meta.created or parse_date(PurePosixPath(rel_path).stem)
    when = committed_at or (local_to_utc(when_local, tz) if when_local else None)

    doc = find_by_source(store, rel_path)
    slug = doc.slug if doc else preferred_slug(rel_path)
    if doc is None and store.get(slug) is not None:
        p = PurePosixPath(rel_path)
        slug = pub.unique_slug(store, text.slugify(f"{p.parent.name}-{p.stem}"))

    if doc is not None:
        # the same body under an older version: the repository is echoing back
        # what the site has already moved past (a full re-sync), not an edit
        incoming = text.body_sha(source, kind)
        latest = store.get_version(doc.slug, None)
        if (
            latest is not None
            and text.body_sha(latest.content, kind) != incoming
            and any(text.body_sha(v.content, kind) == incoming for v in store.versions(doc.slug))
        ):
            return PublishResult(doc, latest, "unchanged")

    result = pub.publish(
        store,
        PublishRequest(
            title=meta.title,
            content=source,
            kind=kind,
            category=category_of(rel_path),
            author=author or meta.author,
            slug=slug,
            tags=meta.tags,
            summary=meta.summary,
            status=meta.status,
            label=label,
            source_path=rel_path,
            created_at=when,
        ),
    )
    if result.outcome == "unchanged" and kind == "md":
        # the body is what versions track; frontmatter edits (tags, status,
        # title) and summary rules still land on the document
        doc = result.doc
        wanted_meta: dict = {"title": meta.title, "summary": meta.summary or None}
        if "tags" in meta.explicit:
            wanted_meta["tags"] = meta.tags
        if "status" in meta.explicit:
            wanted_meta["status"] = meta.status
        changes = {k: v for k, v in wanted_meta.items() if v is not None and getattr(doc, k) != v}
        if changes:
            doc = pub.update_meta(store, doc.slug, **changes)
            return PublishResult(doc, result.version, result.outcome)
    return result


def archive_path(store: DocumentStore, rel_path: str) -> Document | None:
    """A file deleted from the repository: archive its document (URL keeps answering)."""
    doc = find_by_source(store, rel_path)
    if doc is not None and not doc.is_archived:
        doc = pub.archive(store, doc.slug)
    return doc
