"""Text rules shared by every entry point: slugs, categories, summaries, the
body hash that ignores frontmatter, search snippets."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import secrets

# file stems too generic to be a slug on their own (README.md in every directory)
GENERIC_STEMS = {
    "readme",
    "index",
    "overview",
    "prd",
    "changelog",
    "claude",
    "notes",
    "summary",
    "todo",
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)


def slugify(text: str) -> str:
    return _SLUG_RE.sub("-", (text or "").lower()).strip("-")[:80]


def normalize_category(category: str | None) -> str:
    parts = [
        p
        for p in re.split(r"[\\/]+", (category or "").strip().lower())
        if p and p not in (".", "..")
    ]
    return "/".join(parts) or "misc"


def auto_summary(text: str, limit: int = 160) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def body_of(content: str, kind: str = "md") -> str:
    """The document without its frontmatter, for change detection: the
    repository write-back adds frontmatter to a document that had none, and
    that must not read as a new version when the file comes back."""
    if kind == "md":
        content = _FRONTMATTER.sub("", content, count=1)
    return content.strip()


def body_sha(content: str, kind: str = "md") -> str:
    return hashlib.sha256(body_of(content, kind).encode("utf-8")).hexdigest()


def content_sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def make_slug(title: str, preferred: str | None, when: dt.datetime) -> str:
    """An explicit slug is honoured as given (after slugify); otherwise derive one
    from the title, falling back to date + short random id for non-ASCII titles."""
    if preferred and (base := slugify(preferred)):
        return base
    base = slugify(title)
    if len(base) < 3:
        base = f"{when.strftime('%Y%m%d')}-{secrets.token_hex(2)}"
    return base


def snippet(text: str, q: str, width: int = 90) -> str:
    if not text:
        return ""
    idx = text.lower().find(q.lower())
    if idx < 0:
        return text[: width * 2] + ("…" if len(text) > width * 2 else "")
    start = max(0, idx - width)
    end = min(len(text), idx + len(q) + width)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


def natural_key(text: str) -> list:
    """Sort key that orders embedded numbers numerically ("2" before "10")."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text)]
