"""Mark the initial administrator as pending setup."""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('setup_required', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('user') as batch:
        batch.drop_column('setup_required')
