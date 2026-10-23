"""Initial shared cloud schema."""
from alembic import op
from migrations.schema_v1 import metadata, SCHEMAS, install_ownership_guards

revision = "0001_cloud"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for schema in SCHEMAS:
            op.execute('CREATE SCHEMA IF NOT EXISTS "' + schema + '"')
    metadata.create_all(bind)
    install_ownership_guards(bind)


def downgrade():
    # Explicit destructive operation; normal rollout restores from a verified
    # backup after exporting writes, never automatically downgrades production.
    metadata.drop_all(op.get_bind())
