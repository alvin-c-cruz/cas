"""add products.category_id (product line tag)

Revision ID: prodcat_0002
Revises: prodcat_0001
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa

revision = 'prodcat_0002'
down_revision = 'prodcat_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_column('category_id')
