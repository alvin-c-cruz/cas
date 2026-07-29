"""add customer_code to products

Revision ID: prodcc_0001
Revises: drnotes_0001
Create Date: 2026-07-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'prodcc_0001'
down_revision = 'drnotes_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.add_column(sa.Column('customer_code', sa.String(length=50), nullable=True))


def downgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_column('customer_code')
