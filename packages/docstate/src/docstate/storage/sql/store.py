"""The SQL adapter: SQLAlchemy sessions behind the DocumentStore / StateStore
ports. A `transaction()` block binds one session to the calling context; the
methods inside it share that session and the block commits once. Outside a
block every method is its own short transaction."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import Engine, and_, create_engine, desc, event, func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

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
from docstate.core.text import normalize_category

from ..base import StorageError
from .migrate import upgrade
from .models import Models, build_models


def normalize_url(url: str) -> str:
    """Point bare URLs at the drivers this package ships with: psycopg 3 for
    PostgreSQL, PyMySQL for MySQL / MariaDB. Explicit drivers are kept."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    for prefix in ("mysql://", "mariadb://"):
        if url.startswith(prefix):
            return "mysql+pymysql://" + url[len(prefix) :]
    return url


def make_engine(url: str) -> Engine:
    """Engine with the dialect-specific setup: SQLite gets its directory, WAL
    and foreign keys; server databases get pool pre-ping."""
    url = normalize_url(url)
    is_sqlite = url.startswith("sqlite")
    if is_sqlite and "sqlite:///" in url:
        path = url.split("sqlite:///", 1)[1].split("?", 1)[0]
        if path and path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False} if is_sqlite else {},
        pool_pre_ping=not is_sqlite,
    )
    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def redact(url: str) -> str:
    parts = urlsplit(url)
    return url.replace(parts.password, "***") if parts.password else url


def _tags(raw: str | None) -> list[str]:
    try:
        return [str(t) for t in json.loads(raw or "[]")]
    except ValueError:
        return []


def _doc(row) -> Document:
    return Document(
        slug=row.slug,
        title=row.title,
        category=row.category,
        kind=row.kind,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        tags=_tags(row.tags_json),
        summary=row.summary or "",
        status=row.status,
        latest_version=row.latest_version,
        archived_at=row.archived_at,
    )


def _ver(row, slug: str) -> Version:
    return Version(
        slug=slug,
        version_no=row.version_no,
        content=row.content,
        content_sha=row.content_sha,
        size_bytes=row.size_bytes,
        created_by=row.created_by,
        created_at=row.created_at,
        label=row.label or "",
        text_plain=row.text_plain or "",
        source_path=row.source_path,
    )


def _binding(row) -> RepoBinding:
    return RepoBinding(
        slug=row.slug,
        path=row.path,
        synced_version=row.synced_version,
        synced_sha=row.synced_sha,
        meta_sha=row.meta_sha,
        pr_number=row.pr_number,
        pr_url=row.pr_url,
        pr_state=row.pr_state,
        pending_action=row.pending_action,
        pending_version=row.pending_version,
        deleted_at=row.deleted_at,
        last_error=row.last_error,
        updated_at=row.updated_at,
    )


class SqlDocumentStore:
    def __init__(self, engine: Engine, models: Models):
        self.m = models
        self._factory = sessionmaker(engine, expire_on_commit=False)
        self._ambient: ContextVar[Session | None] = ContextVar(
            f"docstate_sql_session_{id(self)}", default=None
        )

    # --- sessions
    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._ambient.get() is not None:
            yield  # join the enclosing block
            return
        session = self._factory()
        token = self._ambient.set(session)
        try:
            yield
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            self._ambient.reset(token)
            session.close()

    @contextmanager
    def _session(self) -> Iterator[Session]:
        ambient = self._ambient.get()
        if ambient is not None:
            yield ambient  # the block's commit covers this
            return
        session = self._factory()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def _row(self, s: Session, slug: str):
        return s.scalar(select(self.m.Doc).where(self.m.Doc.slug == slug))

    def _cat_filter(self, category: str):
        D = self.m.Doc
        category = normalize_category(category)
        return or_(D.category == category, D.category.like(category + "/%"))

    # --- documents
    def get(self, slug: str) -> Document | None:
        with self._session() as s:
            row = self._row(s, slug)
            return _doc(row) if row is not None else None

    def slug_exists(self, slug: str) -> bool:
        with self._session() as s:
            return s.scalar(select(self.m.Doc.id).where(self.m.Doc.slug == slug)) is not None

    def by_title(self, title: str) -> Document | None:
        with self._session() as s:
            row = s.scalar(select(self.m.Doc).where(self.m.Doc.title == title).limit(1))
            return _doc(row) if row is not None else None

    def by_slug_suffix(self, suffix: str) -> Document | None:
        with self._session() as s:
            row = s.scalar(select(self.m.Doc).where(self.m.Doc.slug.like(f"%{suffix}")).limit(1))
            return _doc(row) if row is not None else None

    def by_source_path(self, path: str) -> Document | None:
        D, V, R = self.m.Doc, self.m.DocVersion, self.m.RepoSync
        wanted = path.lower()
        with self._session() as s:
            doc_id = s.scalar(
                select(V.doc_id)
                .where(func.lower(V.source_path) == wanted)
                .order_by(V.version_no)
                .limit(1)
            )
            if doc_id is not None:
                row = s.get(D, doc_id)
                return _doc(row) if row is not None else None
            slug = s.scalar(select(R.slug).where(func.lower(R.path) == wanted).limit(1))
            if slug is None:
                return None
            row = self._row(s, slug)
            return _doc(row) if row is not None else None

    def list(self, query: DocQuery) -> list[Document]:
        D = self.m.Doc
        stmt = select(D).where(D.archived_at.is_(None))
        if query.category:
            stmt = stmt.where(self._cat_filter(query.category))
        if query.tag:
            stmt = stmt.where(D.tags_json.like(f'%"{query.tag}"%'))
        if query.status:
            stmt = stmt.where(D.status == query.status)
        if query.q:
            like = f"%{query.q}%"
            stmt = stmt.where(
                or_(D.title.ilike(like), D.summary.ilike(like), D.tags_json.ilike(like))
            )
        stmt = stmt.order_by(desc(D.updated_at), desc(D.id)).limit(query.limit)
        with self._session() as s:
            return [_doc(r) for r in s.scalars(stmt)]

    def iter_all(self) -> Iterable[Document]:
        D = self.m.Doc
        with self._session() as s:
            return [_doc(r) for r in s.scalars(select(D).order_by(D.updated_at, D.id))]

    def tree_rows(self) -> list[TreeRow]:
        D, V = self.m.Doc, self.m.DocVersion
        first = select(V.doc_id, V.source_path).where(V.version_no == 1).subquery()
        stmt = (
            select(D.category, D.slug, D.title, D.kind, first.c.source_path)
            .join(first, first.c.doc_id == D.id, isouter=True)
            .where(D.archived_at.is_(None))
        )
        with self._session() as s:
            return [TreeRow(*row) for row in s.execute(stmt).all()]

    def timeline(self, category: str | None, limit: int) -> list[TimelineEntry]:
        D, V = self.m.Doc, self.m.DocVersion
        stmt = select(V, D).join(D, V.doc_id == D.id).where(D.archived_at.is_(None))
        if category:
            stmt = stmt.where(self._cat_filter(category))
        stmt = stmt.order_by(desc(V.created_at), desc(V.id)).limit(limit)
        with self._session() as s:
            return [TimelineEntry(_ver(v, d.slug), _doc(d)) for v, d in s.execute(stmt).all()]

    def search(self, q: str, limit: int) -> list[tuple[Document, str]]:
        D, V = self.m.Doc, self.m.DocVersion
        like = f"%{q}%"
        stmt = (
            select(D, V.text_plain)
            .join(V, and_(V.doc_id == D.id, V.version_no == D.latest_version))
            .where(D.archived_at.is_(None))
            .where(
                or_(
                    D.title.ilike(like),
                    D.summary.ilike(like),
                    D.tags_json.ilike(like),
                    V.text_plain.ilike(like),
                )
            )
            .order_by(desc(D.updated_at))
            .limit(limit)
        )
        with self._session() as s:
            return [(_doc(d), plain or "") for d, plain in s.execute(stmt).all()]

    def create(self, doc: Document) -> Document:
        with self._session() as s:
            if self._row(s, doc.slug) is not None:
                raise StorageError(f"slug {doc.slug!r} already exists")
            s.add(
                self.m.Doc(
                    slug=doc.slug,
                    title=doc.title,
                    category=doc.category,
                    tags_json=json.dumps(doc.tags, ensure_ascii=False),
                    summary=doc.summary,
                    status=doc.status,
                    kind=doc.kind,
                    created_by=doc.created_by,
                    created_at=doc.created_at,
                    updated_at=doc.updated_at,
                    latest_version=doc.latest_version,
                    archived_at=doc.archived_at,
                )
            )
            s.flush()
        return doc

    def update(self, doc: Document) -> Document:
        with self._session() as s:
            row = self._row(s, doc.slug)
            if row is None:
                raise StorageError(f"no document {doc.slug!r}")
            row.title = doc.title
            row.category = doc.category
            row.tags_json = json.dumps(doc.tags, ensure_ascii=False)
            row.summary = doc.summary
            row.status = doc.status
            row.kind = doc.kind
            row.updated_at = doc.updated_at
            row.latest_version = doc.latest_version
            row.archived_at = doc.archived_at
            s.flush()
        return doc

    # --- versions
    def get_version(self, slug: str, version_no: int | None) -> Version | None:
        V = self.m.DocVersion
        with self._session() as s:
            row = self._row(s, slug)
            if row is None:
                return None
            n = version_no or row.latest_version
            v = s.scalar(select(V).where(V.doc_id == row.id, V.version_no == n))
            return _ver(v, slug) if v is not None else None

    def versions(self, slug: str) -> list[Version]:
        V = self.m.DocVersion
        with self._session() as s:
            row = self._row(s, slug)
            if row is None:
                return []
            rows = s.scalars(select(V).where(V.doc_id == row.id).order_by(desc(V.version_no)))
            return [_ver(v, slug) for v in rows]

    def add_version(self, version: Version) -> Version:
        with self._session() as s:
            row = self._row(s, version.slug)
            if row is None:
                raise StorageError(f"no document {version.slug!r}")
            s.add(
                self.m.DocVersion(
                    doc_id=row.id,
                    version_no=version.version_no,
                    label=version.label,
                    content=version.content,
                    text_plain=version.text_plain,
                    content_sha=version.content_sha,
                    size_bytes=version.size_bytes,
                    source_path=version.source_path,
                    created_by=version.created_by,
                    created_at=version.created_at,
                )
            )
            s.flush()
        return version

    # --- repository bindings
    def repo_binding(self, slug: str) -> RepoBinding | None:
        with self._session() as s:
            row = s.get(self.m.RepoSync, slug)
            return _binding(row) if row is not None else None

    def save_repo_binding(self, binding: RepoBinding) -> RepoBinding:
        R = self.m.RepoSync
        with self._session() as s:
            if self._row(s, binding.slug) is None:
                raise StorageError(f"no document {binding.slug!r}")
            row = s.get(R, binding.slug)
            if row is None:
                row = R(slug=binding.slug, path=binding.path, updated_at=utcnow())
                s.add(row)
            for name in (
                "path",
                "synced_version",
                "synced_sha",
                "meta_sha",
                "pr_number",
                "pr_url",
                "pr_state",
                "pending_action",
                "pending_version",
                "deleted_at",
                "last_error",
            ):
                setattr(row, name, getattr(binding, name))
            row.updated_at = binding.updated_at or utcnow()
            binding.updated_at = row.updated_at
            s.flush()
        return binding

    def repo_bindings(self, pr_state: str | None = None) -> list[RepoBinding]:
        R = self.m.RepoSync
        stmt = select(R)
        if pr_state is not None:
            stmt = stmt.where(R.pr_state == pr_state)
        with self._session() as s:
            return [_binding(r) for r in s.scalars(stmt)]


class SqlStateStore:
    def __init__(self, engine: Engine, models: Models):
        self.m = models
        self._factory = sessionmaker(engine, expire_on_commit=False)

    @staticmethod
    def _entry(row) -> StateEntry:
        try:
            value = json.loads(row.value_json)
        except ValueError:
            value = None
        return StateEntry(row.slug, row.key, row.viewer, value, row.updated_by, row.updated_at)

    def get(self, slug: str, key: str, viewer: str) -> StateEntry | None:
        with self._factory() as s:
            row = s.get(self.m.DocState, (slug, key, viewer))
            return self._entry(row) if row is not None else None

    def set(self, slug: str, key: str, viewer: str, value: Any, by: str) -> StateEntry:
        with self._factory() as s:
            row = s.get(self.m.DocState, (slug, key, viewer))
            if row is None:
                row = self.m.DocState(slug=slug, key=key, viewer=viewer)
                s.add(row)
            row.value_json = json.dumps(value, ensure_ascii=False)
            row.updated_by = by
            row.updated_at = utcnow()
            s.commit()
            return self._entry(row)


class SqlStorage:
    def __init__(
        self, url: str, *, state_url: str = "", table_prefix: str = "", schema: str = "", **_opts
    ):
        self.url = normalize_url(url)
        state_url = normalize_url(state_url) if state_url else ""
        self.state_url = state_url if state_url and state_url != self.url else ""
        self.engine = make_engine(url)
        self.state_engine = make_engine(self.state_url) if self.state_url else self.engine
        self.models = build_models(table_prefix, self._schema_for(self.engine, schema))
        self.state_models = build_models(table_prefix, self._schema_for(self.state_engine, schema))
        self.docs = SqlDocumentStore(self.engine, self.models)
        self.state = SqlStateStore(self.state_engine, self.state_models)

    @staticmethod
    def _schema_for(engine: Engine, schema: str) -> str | None:
        return None if engine.dialect.name == "sqlite" else (schema.strip() or None)

    def init(self) -> None:
        upgrade(self.engine, table_prefix=self.models.prefix, schema=self.models.schema)
        if self.state_engine is not self.engine:
            upgrade(
                self.state_engine,
                table_prefix=self.state_models.prefix,
                schema=self.state_models.schema,
            )

    def ping(self) -> None:
        for engine in {
            id(self.engine): self.engine,
            id(self.state_engine): self.state_engine,
        }.values():
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
            except SQLAlchemyError as exc:
                raise StorageError(f"database not reachable: {exc}") from exc

    def close(self) -> None:
        self.engine.dispose()
        if self.state_engine is not self.engine:
            self.state_engine.dispose()

    def describe(self) -> str:
        parts = [f"sql {redact(self.url)}"]
        if self.state_url:
            parts.append(f"state {redact(self.state_url)}")
        if self.models.prefix:
            parts.append(f"prefix={self.models.prefix!r}")
        if self.models.schema:
            parts.append(f"schema={self.models.schema!r}")
        return " · ".join(parts)

    def clear(self) -> None:
        """Tests only: empty every table, keep the schema."""
        for engine, models in ((self.engine, self.models), (self.state_engine, self.state_models)):
            with engine.begin() as conn:
                for table in reversed(models.metadata.sorted_tables):
                    conn.execute(table.delete())


def open_sql_storage(url: str, *, state_url: str = "", **options) -> SqlStorage:
    return SqlStorage(url, state_url=state_url, **options)
