"""Alembic, driven from code: no alembic.ini, the connection and the table
prefix travel in `config.attributes`. `upgrade()` is what `docstate migrate`
and the startup auto-migration call."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

ALEMBIC_DIR = Path(__file__).parent / "alembic"


def _config(prefix: str, schema: str | None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    cfg.attributes["table_prefix"] = prefix
    cfg.attributes["schema"] = schema
    return cfg


def upgrade(engine: Engine, *, table_prefix: str = "", schema: str | None = None) -> None:
    """Bring the database to the newest revision (creating the schema first on
    PostgreSQL when one is configured)."""
    if schema and engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    cfg = _config(table_prefix, schema)
    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


def current_revision(
    engine: Engine, *, table_prefix: str = "", schema: str | None = None
) -> str | None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn,
            opts={
                "version_table": f"{table_prefix}alembic_version",
                "version_table_schema": schema,
            },
        )
        return ctx.get_current_revision()


def head_revision() -> str | None:
    return ScriptDirectory.from_config(_config("", None)).get_current_head()
