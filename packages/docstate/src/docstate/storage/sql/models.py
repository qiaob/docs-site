"""ORM tables. Built per (prefix, schema) so one process can talk to a shared
database under a table prefix without touching global state. Four tables:

    docs          one row per document (the stable URL)
    doc_versions  immutable content revisions
    doc_state     per-document key/value state, keyed by slug so it can live in
                  another database than the documents
    repo_sync     where a document lives in a git repository (write-back)
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from functools import cache

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


@dataclass(frozen=True)
class Models:
    prefix: str
    schema: str | None
    metadata: MetaData
    Doc: type
    DocVersion: type
    DocState: type
    RepoSync: type

    def table(self, name: str) -> str:
        return f"{self.prefix}{name}"


@cache
def build_models(prefix: str = "", schema: str | None = None) -> Models:
    schema = schema or None
    fq = (schema + ".") if schema else ""

    class Base(DeclarativeBase):
        metadata = MetaData(schema=schema)

    class Doc(Base):
        __tablename__ = f"{prefix}docs"
        __table_args__ = (Index(f"ix_{prefix}docs_updated_at", "updated_at"),)

        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
        title: Mapped[str] = mapped_column(String(500))
        category: Mapped[str] = mapped_column(String(200), index=True)
        tags_json: Mapped[str] = mapped_column(Text, default="[]")
        summary: Mapped[str] = mapped_column(Text, default="")
        status: Mapped[str] = mapped_column(String(20), default="draft")
        kind: Mapped[str] = mapped_column(String(10))
        created_by: Mapped[str] = mapped_column(String(200))
        created_at: Mapped[dt.datetime] = mapped_column(DateTime)
        updated_at: Mapped[dt.datetime] = mapped_column(DateTime)
        latest_version: Mapped[int] = mapped_column(Integer, default=0)
        archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    class DocVersion(Base):
        __tablename__ = f"{prefix}doc_versions"
        __table_args__ = (
            UniqueConstraint("doc_id", "version_no", name=f"uq_{prefix}doc_versions_doc_no"),
            Index(f"ix_{prefix}doc_versions_source_path", "source_path"),
            Index(f"ix_{prefix}doc_versions_created_at", "created_at"),
        )

        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        doc_id: Mapped[int] = mapped_column(ForeignKey(f"{fq}{prefix}docs.id"), index=True)
        version_no: Mapped[int] = mapped_column(Integer)
        label: Mapped[str] = mapped_column(String(200), default="")
        content: Mapped[str] = mapped_column(Text)
        text_plain: Mapped[str] = mapped_column(Text, default="")
        content_sha: Mapped[str] = mapped_column(String(64))
        size_bytes: Mapped[int] = mapped_column(Integer)
        source_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
        created_by: Mapped[str] = mapped_column(String(200))
        created_at: Mapped[dt.datetime] = mapped_column(DateTime)

    class DocState(Base):
        __tablename__ = f"{prefix}doc_state"

        slug: Mapped[str] = mapped_column(String(200), primary_key=True)
        key: Mapped[str] = mapped_column(String(200), primary_key=True)
        viewer: Mapped[str] = mapped_column(String(200), primary_key=True, default="")
        value_json: Mapped[str] = mapped_column(Text, default="null")
        updated_by: Mapped[str] = mapped_column(String(200))
        updated_at: Mapped[dt.datetime] = mapped_column(DateTime)

    class RepoSync(Base):
        __tablename__ = f"{prefix}repo_sync"
        __table_args__ = (Index(f"ix_{prefix}repo_sync_path", "path"),)

        slug: Mapped[str] = mapped_column(
            String(200), ForeignKey(f"{fq}{prefix}docs.slug"), primary_key=True
        )
        path: Mapped[str] = mapped_column(String(500))
        synced_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
        synced_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
        meta_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
        pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
        pr_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
        pr_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
        pending_action: Mapped[str | None] = mapped_column(String(10), nullable=True)
        pending_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
        deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
        last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
        updated_at: Mapped[dt.datetime] = mapped_column(DateTime)

    return Models(prefix, schema, Base.metadata, Doc, DocVersion, DocState, RepoSync)
