"""Storage adapters and their factory.

    storage = open_storage("sqlite:///data/docstate.db")
    storage = open_storage("postgresql://user:pw@host/db", state_url="redis://...")  # later
    storage = open_storage("memory://")

The scheme picks the adapter: `sqlite`, `postgresql`, `postgres`, `mysql` and
`mariadb` are the SQL adapter, `memory` the in-memory one. Any other scheme is
looked up among the `docstate.storage` entry points, so a third-party package
can add a backend without touching this code."""

from __future__ import annotations

from importlib.metadata import entry_points
from urllib.parse import urlsplit

from .base import DocumentStore, StateStore, Storage, StorageError

__all__ = ["DocumentStore", "StateStore", "Storage", "StorageError", "open_storage"]

_SQL_SCHEMES = {"sqlite", "postgresql", "postgres", "mysql", "mariadb"}


def scheme_of(url: str) -> str:
    scheme = urlsplit(url).scheme.lower()
    return scheme.split("+", 1)[0]  # postgresql+psycopg -> postgresql


def open_storage(url: str, *, state_url: str = "", **options) -> Storage:
    """Build the storage behind `url`. `state_url` may point the state port at
    a different backend; empty means the same one. `options` are passed to the
    adapter (the SQL one takes `table_prefix` and `schema`)."""
    scheme = scheme_of(url)
    if scheme in _SQL_SCHEMES:
        from .sql import open_sql_storage

        return open_sql_storage(url, state_url=state_url, **options)
    if scheme == "memory":
        from .memory import open_memory_storage

        return open_memory_storage(url, state_url=state_url, **options)
    for ep in entry_points(group="docstate.storage"):
        if ep.name == scheme:
            factory = ep.load()
            return factory(url, state_url=state_url, **options)
    raise StorageError(f"no storage adapter for scheme {scheme!r} (url: {_redact(url)})")


def _redact(url: str) -> str:
    parts = urlsplit(url)
    if parts.password:
        return url.replace(parts.password, "***")
    return url
