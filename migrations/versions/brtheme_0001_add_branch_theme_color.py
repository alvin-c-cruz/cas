"""add branch theme_color

Revision ID: brtheme_0001
Revises: drje_0001
"""
import sqlalchemy as sa
from alembic import op

revision = 'brtheme_0001'
down_revision = 'drje_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('branches') as batch_op:
        batch_op.add_column(sa.Column('theme_color', sa.String(length=7), nullable=True))


def downgrade():
    with op.batch_alter_table('branches') as batch_op:
        batch_op.drop_column('theme_color')
