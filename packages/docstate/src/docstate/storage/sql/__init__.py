"""SQL storage on SQLAlchemy: SQLite, PostgreSQL (psycopg 3), MySQL / MariaDB
(PyMySQL). Schema managed by Alembic (`docstate migrate`, or automatically at
startup with DOCSTATE_AUTO_MIGRATE)."""

from .store import SqlStorage, open_sql_storage

__all__ = ["SqlStorage", "open_sql_storage"]
