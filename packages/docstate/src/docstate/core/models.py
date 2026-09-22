"""Domain model as plain dataclasses. Every storage adapter returns these, and
the server, the CLI, the static builder and the MCP package only ever see
these — never an ORM row."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

STATUSES = ("draft", "review", "approved", "deprecated")
KINDS = ("md", "html")
OUTCOMES = ("created", "new_version", "unchanged")


@dataclass(frozen=True)
class Document:
    """A published document: one stable URL (`/d/<slug>`), any number of versions."""

    slug: str
    title: str
    category: str  # directory-like path, e.g. "guides/onboarding"
    kind: str  # md | html
    created_by: str
    created_at: dt.datetime  # naive UTC
    updated_at: dt.datetime  # naive UTC
    tags: list[str] = field(default_factory=list)
    summary: str = ""
    status: str = "draft"
    latest_version: int = 0
    archived_at: dt.datetime | None = None

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


@dataclass(frozen=True)
class Version:
    """One immutable revision of a document's content."""

    slug: str
    version_no: int
    content: str
    content_sha: str
    size_bytes: int
    created_by: str
    created_at: dt.datetime  # naive UTC
    label: str = ""
    text_plain: str = ""  # what search indexes
    source_path: str | None = None  # repository path this version came from, if any


@dataclass(frozen=True)
class StateEntry:
    """Per-document key/value state. `viewer == ""` is the shared scope."""

    slug: str
    key: str
    viewer: str
    value: Any
    updated_by: str
    updated_at: dt.datetime


@dataclass
class RepoBinding:
    """Where a document lives in a git repository and what was last written
    there (the GitHub write-back integration keeps this current). Mutable: it
    is a record that gets updated in place, not a value."""

    slug: str
    path: str
    synced_version: int | None = None
    synced_sha: str | None = None  # sha256 of the exported text
    meta_sha: str | None = None  # sha256 of title/tags/status/category
    pr_number: int | None = None
    pr_url: str | None = None
    pr_state: str | None = None  # merged | open
    pending_action: str | None = None  # write | delete (what an open PR would do)
    pending_version: int | None = None
    deleted_at: dt.datetime | None = None
    last_error: str | None = None
    updated_at: dt.datetime | None = None


@dataclass(frozen=True)
class TreeRow:
    """What the sidebar tree is built from: one live document."""

    category: str
    slug: str
    title: str
    kind: str
    source_path: str | None  # of the first version (the repository file name)


@dataclass(frozen=True)
class TimelineEntry:
    version: Version
    doc: Document


@dataclass(frozen=True)
class SearchHit:
    doc: Document
    snippet: str


@dataclass
class DocQuery:
    category: str | None = None  # this category and everything below it
    tag: str | None = None
    status: str | None = None
    q: str | None = None  # substring of title / summary / tags
    limit: int = 500


@dataclass
class PublishRequest:
    title: str
    content: str
    kind: str
    category: str
    author: str
    slug: str | None = None
    tags: list[str] | None = None
    summary: str | None = None
    label: str | None = None
    source_path: str | None = None
    status: str | None = None
    created_at: dt.datetime | None = None  # naive UTC; defaults to now


@dataclass(frozen=True)
class PublishResult:
    doc: Document
    version: Version
    outcome: str  # created | new_version | unchanged

    def __iter__(self):
        """Allows `doc, version, outcome = publish(...)`."""
        yield self.doc
        yield self.version
        yield self.outcome
