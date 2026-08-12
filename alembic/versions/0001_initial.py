"""Initial AMLGuard schemas and tables."""

from alembic import op
from amlguard.db import models as _models  # noqa: F401
from amlguard.db.base import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

SCHEMAS = ("bank", "casework", "policy", "audit", "experiment", "langgraph")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
    for schema in reversed(SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
