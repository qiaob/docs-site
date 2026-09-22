"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def _names():
    cfg = op.get_context().config
    return cfg.attributes.get("table_prefix") or "", cfg.attributes.get("schema")


def upgrade() -> None:
    prefix, schema = _names()
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    prefix, schema = _names()
    ${downgrades if downgrades else "pass"}
