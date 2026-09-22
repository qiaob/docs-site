"""In-memory storage: tests, demos and the static builder's scratch space.
Nothing survives the process; `transaction()` groups nothing (there is no
rollback), which is fine for those uses."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from copy import deepcopy
from typing import Any

from docstate.core.clock import utcnow
from docstate.core.models import (
    DocQuery,
    Document,
    RepoBinding,
    StateEntry,
    TimelineEntry,
    TreeRow,
    Version,
)

from .base import StorageError


def _cat_match(doc_category: str, wanted: str) -> bool:
    return doc_category == wanted or doc_category.startswith(wanted + "/")


class MemoryDocumentStore:
    def __init__(self) -> None:
        self._docs: dict[str, Document] = {}
        self._versions: dict[str, list[Version]] = {}  # oldest first
        self._bindings: dict[str, RepoBinding] = {}
        self._serials: dict[str, int] = {}
        self._order = 0  # insertion order breaks ties like a serial id would

    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield

    # --- documents
    def get(self, slug: str) -> Document | None:
        return self._docs.get(slug)

    def slug_exists(self, slug: str) -> bool:
        return slug in self._docs

    def by_title(self, title: str) -> Document | None:
        return next((d for d in self._docs.values() if d.title == title), None)

    def by_slug_suffix(self, suffix: str) -> Document | None:
        return next((d for d in self._docs.values() if d.slug.endswith(suffix)), None)

    def by_source_path(self, path: str) -> Document | None:
        wanted = path.lower()
        best: tuple[int, Version] | None = None
        for versions in self._versions.values():
            for v in versions:
                if v.source_path and v.source_path.lower() == wanted:
                    if best is None or v.version_no < best[1].version_no:
                        best = (0, v)
                    break
        if best is not None:
            return self._docs.get(best[1].slug)
        for b in self._bindings.values():
            if b.path.lower() == wanted:
                return self._docs.get(b.slug)
        return None

    def list(self, query: DocQuery) -> list[Document]:
        out = [d for d in self._docs.values() if not d.is_archived]
        if query.category:
            from docstate.core.text import normalize_category

            cat = normalize_category(query.category)
            out = [d for d in out if _cat_match(d.category, cat)]
        if query.tag:
            out = [d for d in out if query.tag in d.tags]
        if query.status:
            out = [d for d in out if d.status == query.status]
        if query.q:
            q = query.q.lower()
            out = [
                d
                for d in out
                if q in d.title.lower()
                or q in d.summary.lower()
                or any(q in t.lower() for t in d.tags)
            ]
        out.sort(key=lambda d: (d.updated_at, self._serial(d.slug)), reverse=True)
        return out[: query.limit]

    def iter_all(self) -> Iterable[Document]:
        return sorted(self._docs.values(), key=lambda d: (d.updated_at, self._serial(d.slug)))

    def tree_rows(self) -> list[TreeRow]:
        rows = []
        for d in self._docs.values():
            if d.is_archived:
                continue
            first = self._versions.get(d.slug, [None])[0]
            rows.append(
                TreeRow(d.category, d.slug, d.title, d.kind, first.source_path if first else None)
            )
        return rows

    def timeline(self, category: str | None, limit: int) -> list[TimelineEntry]:
        entries = []
        for d in self._docs.values():
            if d.is_archived:
                continue
            if category:
                from docstate.core.text import normalize_category

                if not _cat_match(d.category, normalize_category(category)):
                    continue
            entries.extend(TimelineEntry(v, d) for v in self._versions.get(d.slug, []))
        entries.sort(key=lambda e: (e.version.created_at, e.version.version_no), reverse=True)
        return entries[:limit]

    def search(self, q: str, limit: int) -> list[tuple[Document, str]]:
        ql = q.lower()
        hits = []
        for d in self._docs.values():
            if d.is_archived:
                continue
            latest = self._latest(d.slug)
            plain = latest.text_plain if latest else ""
            if (
                ql in d.title.lower()
                or ql in d.summary.lower()
                or any(ql in t.lower() for t in d.tags)
                or ql in plain.lower()
            ):
                hits.append((d, plain))
        hits.sort(key=lambda h: h[0].updated_at, reverse=True)
        return hits[:limit]

    def create(self, doc: Document) -> Document:
        if doc.slug in self._docs:
            raise StorageError(f"slug {doc.slug!r} already exists")
        self._order += 1
        self._serials[doc.slug] = self._order
        self._docs[doc.slug] = doc
        self._versions.setdefault(doc.slug, [])
        return doc

    def update(self, doc: Document) -> Document:
        if doc.slug not in self._docs:
            raise StorageError(f"no document {doc.slug!r}")
        self._docs[doc.slug] = doc
        return doc

    # --- versions
    def _latest(self, slug: str) -> Version | None:
        versions = self._versions.get(slug)
        return versions[-1] if versions else None

    def get_version(self, slug: str, version_no: int | None) -> Version | None:
        doc = self._docs.get(slug)
        if doc is None:
            return None
        n = version_no or doc.latest_version
        return next((v for v in self._versions.get(slug, []) if v.version_no == n), None)

    def versions(self, slug: str) -> list[Version]:
        return list(reversed(self._versions.get(slug, [])))

    def add_version(self, version: Version) -> Version:
        if version.slug not in self._docs:
            raise StorageError(f"no document {version.slug!r}")
        self._versions[version.slug].append(version)
        return version

    # --- repository bindings
    def repo_binding(self, slug: str) -> RepoBinding | None:
        b = self._bindings.get(slug)
        return deepcopy(b) if b else None

    def save_repo_binding(self, binding: RepoBinding) -> RepoBinding:
        if binding.slug not in self._docs:
            raise StorageError(f"no document {binding.slug!r}")
        binding.updated_at = binding.updated_at or utcnow()
        self._bindings[binding.slug] = deepcopy(binding)
        return binding

    def repo_bindings(self, pr_state: str | None = None) -> list[RepoBinding]:
        return [
            deepcopy(b)
            for b in self._bindings.values()
            if pr_state is None or b.pr_state == pr_state
        ]

    # --- helpers
    def _serial(self, slug: str) -> int:
        return self._serials.get(slug, 0)

    def clear(self) -> None:
        self._docs.clear()
        self._versions.clear()
        self._bindings.clear()
        self._serials.clear()


class MemoryStateStore:
    def __init__(self) -> None:
        self._state: dict[tuple[str, str, str], StateEntry] = {}

    def get(self, slug: str, key: str, viewer: str) -> StateEntry | None:
        return self._state.get((slug, key, viewer))

    def set(self, slug: str, key: str, viewer: str, value: Any, by: str) -> StateEntry:
        entry = StateEntry(slug, key, viewer, deepcopy(value), by, utcnow())
        self._state[(slug, key, viewer)] = entry
        return entry

    def clear(self) -> None:
        self._state.clear()


class MemoryStorage:
    def __init__(self) -> None:
        self.docs = MemoryDocumentStore()
        self.state = MemoryStateStore()
        self.created_at: dt.datetime = utcnow()

    def init(self) -> None:
        pass

    def ping(self) -> None:
        pass

    def close(self) -> None:
        pass

    def describe(self) -> str:
        return "memory (nothing is persisted)"

    def clear(self) -> None:
        self.docs.clear()
        self.state.clear()


def open_memory_storage(
    url: str = "memory://", *, state_url: str = "", **_options
) -> MemoryStorage:
    return MemoryStorage()
