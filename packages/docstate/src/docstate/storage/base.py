"""Storage ports.

Two ports, not one: documents and their state have different deployment
stories. Documents can be static or come from git; state is always written
live. Keeping them apart is what lets a static site put its documents on
GitHub Pages and its state in Cloudflare KV.

Adapters implement these protocols and are picked by URL scheme
(`storage.open_storage`). The rules — what counts as a new version, how slugs
are made, how the tree is sorted — live in `docstate.core`, so every adapter
stays thin and the rules exist once."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import AbstractContextManager
from typing import Any, Protocol, runtime_checkable

from docstate.core.models import (
    DocQuery,
    Document,
    RepoBinding,
    StateEntry,
    TimelineEntry,
    TreeRow,
    Version,
)


class StorageError(RuntimeError):
    """The backend is misconfigured or unreachable."""


@runtime_checkable
class DocumentStore(Protocol):
    """Documents, versions and repository bindings."""

    def transaction(self) -> AbstractContextManager[None]:
        """Group several writes; the block commits as one unit (where the
        backend supports it) and joins an enclosing transaction if there is one."""
        ...

    # --- documents
    def get(self, slug: str) -> Document | None: ...
    def slug_exists(self, slug: str) -> bool: ...
    def by_title(self, title: str) -> Document | None: ...
    def by_slug_suffix(self, suffix: str) -> Document | None: ...
    def by_source_path(self, path: str) -> Document | None:
        """The document behind a repository path: the one whose version came
        from it, or the one the write-back bound to it. Case-insensitive."""
        ...

    def list(self, query: DocQuery) -> list[Document]:
        """Live documents, newest updated first."""
        ...

    def iter_all(self) -> Iterable[Document]:
        """Every document including archived ones, oldest updated first."""
        ...

    def tree_rows(self) -> list[TreeRow]: ...
    def timeline(self, category: str | None, limit: int) -> list[TimelineEntry]:
        """Versions of live documents, newest first."""
        ...

    def search(self, q: str, limit: int) -> list[tuple[Document, str]]:
        """Live documents whose title / summary / tags / latest text contain
        `q`, with the latest version's plain text for the snippet."""
        ...

    def create(self, doc: Document) -> Document: ...
    def update(self, doc: Document) -> Document:
        """Replace the mutable fields of the document with this slug."""
        ...

    # --- versions
    def get_version(self, slug: str, version_no: int | None) -> Version | None:
        """`None` means the latest."""
        ...

    def versions(self, slug: str) -> list[Version]:
        """Newest first, content included."""
        ...

    def add_version(self, version: Version) -> Version: ...

    # --- repository bindings
    def repo_binding(self, slug: str) -> RepoBinding | None: ...
    def save_repo_binding(self, binding: RepoBinding) -> RepoBinding: ...
    def repo_bindings(self, pr_state: str | None = None) -> list[RepoBinding]: ...


@runtime_checkable
class StateStore(Protocol):
    """Per-document key/value state; `viewer == ""` is the shared scope."""

    def get(self, slug: str, key: str, viewer: str) -> StateEntry | None: ...
    def set(self, slug: str, key: str, viewer: str, value: Any, by: str) -> StateEntry: ...


class Storage(Protocol):
    """What `open_storage` returns: both ports plus lifecycle."""

    docs: DocumentStore
    state: StateStore

    def init(self) -> None:
        """Create or migrate the schema. Idempotent."""
        ...

    def ping(self) -> None:
        """Raise StorageError when the backend cannot answer."""
        ...

    def close(self) -> None: ...

    def describe(self) -> str:
        """One line for `docstate check` (never includes credentials)."""
        ...
