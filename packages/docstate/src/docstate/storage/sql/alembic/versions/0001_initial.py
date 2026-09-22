"""Initial schema: docs, doc_versions, doc_state, repo_sync.

Revision ID: 0001
Revises:
Create Date: 2026-09-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _names():
    cfg = op.get_context().config
    return cfg.attributes.get("table_prefix") or "", cfg.attributes.get("schema")


def upgrade() -> None:
    prefix, schema = _names()
    fq = (schema + ".") if schema else ""

    def t(name: str) -> str:
        return f"{prefix}{name}"

    op.create_table(
        t("docs"),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("category", sa.String(200), nullable=False),
        sa.Column("tags_json", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("latest_version", sa.Integer, nullable=False),
        sa.Column("archived_at", sa.DateTime, nullable=True),
        schema=schema,
    )
    op.create_index(f"ix_{t('docs')}_slug", t("docs"), ["slug"], unique=True, schema=schema)
    op.create_index(f"ix_{t('docs')}_category", t("docs"), ["category"], schema=schema)
    op.create_index(f"ix_{t('docs')}_updated_at", t("docs"), ["updated_at"], schema=schema)

    op.create_table(
        t("doc_versions"),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("doc_id", sa.Integer, sa.ForeignKey(f"{fq}{t('docs')}.id"), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("text_plain", sa.Text, nullable=False),
        sa.Column("content_sha", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("source_path", sa.String(500), nullable=True),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("doc_id", "version_no", name=f"uq_{t('doc_versions')}_doc_no"),
        schema=schema,
    )
    op.create_index(f"ix_{t('doc_versions')}_doc_id", t("doc_versions"), ["doc_id"], schema=schema)
    op.create_index(
        f"ix_{t('doc_versions')}_source_path", t("doc_versions"), ["source_path"], schema=schema
    )
    op.create_index(
        f"ix_{t('doc_versions')}_created_at", t("doc_versions"), ["created_at"], schema=schema
    )

    op.create_table(
        t("doc_state"),
        sa.Column("slug", sa.String(200), primary_key=True),
        sa.Column("key", sa.String(200), primary_key=True),
        sa.Column("viewer", sa.String(200), primary_key=True),
        sa.Column("value_json", sa.Text, nullable=False),
        sa.Column("updated_by", sa.String(200), nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        schema=schema,
    )

    op.create_table(
        t("repo_sync"),
        sa.Column("slug", sa.String(200), sa.ForeignKey(f"{fq}{t('docs')}.slug"), primary_key=True),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("synced_version", sa.Integer, nullable=True),
        sa.Column("synced_sha", sa.String(64), nullable=True),
        sa.Column("meta_sha", sa.String(64), nullable=True),
        sa.Column("pr_number", sa.Integer, nullable=True),
        sa.Column("pr_url", sa.String(500), nullable=True),
        sa.Column("pr_state", sa.String(20), nullable=True),
        sa.Column("pending_action", sa.String(10), nullable=True),
        sa.Column("pending_version", sa.Integer, nullable=True),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        schema=schema,
    )
    op.create_index(f"ix_{t('repo_sync')}_path", t("repo_sync"), ["path"], schema=schema)


def downgrade() -> None:
    prefix, schema = _names()
    for name in ("repo_sync", "doc_state", "doc_versions", "docs"):
        op.drop_table(f"{prefix}{name}", schema=schema)
