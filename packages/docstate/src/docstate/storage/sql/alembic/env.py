"""Alembic environment. Only runs through `docstate.storage.sql.migrate`,
which hands over an open connection and the table prefix."""

from alembic import context

config = context.config
connection = config.attributes.get("connection")
if connection is None:
    raise RuntimeError("run migrations through docstate.storage.sql.migrate.upgrade()")

prefix = config.attributes.get("table_prefix") or ""
schema = config.attributes.get("schema")

context.configure(
    connection=connection,
    target_metadata=None,
    version_table=f"{prefix}alembic_version",
    version_table_schema=schema,
    include_schemas=bool(schema),
    render_as_batch=connection.dialect.name == "sqlite",
)

with context.begin_transaction():
    context.run_migrations()
