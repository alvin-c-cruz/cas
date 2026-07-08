"""add salesperson_id to sales_orders and sales_invoices

Revision ID: e95cdff4e8e6
Revises: 0561206ba8e1
Create Date: 2026-07-08 16:37:58.932696

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e95cdff4e8e6'
down_revision = '0561206ba8e1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('sales_orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('salesperson_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_sales_orders_salesperson_id'), ['salesperson_id'])
    with op.batch_alter_table('sales_invoices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('salesperson_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_sales_invoices_salesperson_id'), ['salesperson_id'])


def downgrade():
    with op.batch_alter_table('sales_invoices', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sales_invoices_salesperson_id'))
        batch_op.drop_column('salesperson_id')
    with op.batch_alter_table('sales_orders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sales_orders_salesperson_id'))
        batch_op.drop_column('salesperson_id')
