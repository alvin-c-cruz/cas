"""add products.standard_cost (Phase 3a manual planning cost figure)

Revision ID: isbypl_0001
Revises: 600ef1b526b4
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa

revision = 'isbypl_0001'
down_revision = '600ef1b526b4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.add_column(sa.Column('standard_cost', sa.Numeric(15, 4), nullable=True))


def downgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_column('standard_cost')
