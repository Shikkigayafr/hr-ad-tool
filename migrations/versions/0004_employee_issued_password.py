"""Store encrypted passwords issued by the panel."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("employee", sa.Column("issued_password", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("employee") as batch:
        batch.drop_column("issued_password")
