"""add wt_id to sales_order_items

Revision ID: sowt_0001
Revises: sodl_0001
Create Date: 2026-07-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'sowt_0001'
down_revision = 'sodl_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('sales_order_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('wt_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('sales_order_items', schema=None) as batch_op:
        batch_op.drop_column('wt_id')
