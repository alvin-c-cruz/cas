"""add job_order_name to products

Revision ID: 7f2a91cd44be
Revises: ec44eda6db34
Create Date: 2026-07-17 00:00:00.000000

Optional operations-facing item name, shown on the Job Order Slip print view instead of
the customer-facing `name`. Falls back to `name` at display time when blank (template-level,
no default here). Single nullable column, no FK, no server_default needed.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7f2a91cd44be'
down_revision = 'ec44eda6db34'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.add_column(sa.Column('job_order_name', sa.String(length=200), nullable=True))


def downgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_column('job_order_name')
