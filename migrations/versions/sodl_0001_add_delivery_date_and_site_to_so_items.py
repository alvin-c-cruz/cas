"""add delivery_date and delivery_site_id to sales_order_items

Revision ID: sodl_0001
Revises: cds_0001
Create Date: 2026-07-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'sodl_0001'
down_revision = 'cds_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('sales_order_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('delivery_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('delivery_site_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_sales_order_items_delivery_site_id'), ['delivery_site_id'])


def downgrade():
    with op.batch_alter_table('sales_order_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sales_order_items_delivery_site_id'))
        batch_op.drop_column('delivery_site_id')
        batch_op.drop_column('delivery_date')
