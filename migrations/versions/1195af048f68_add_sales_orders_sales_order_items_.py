"""add sales_orders + sales_order_items tables

Revision ID: 1195af048f68
Revises: 82f53dde7e81
Create Date: 2026-06-28 14:58:34.717342

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1195af048f68'
down_revision = '82f53dde7e81'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sales_orders',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('branch_id', sa.Integer(), nullable=True),
    sa.Column('so_number', sa.String(length=50), nullable=False),
    sa.Column('order_date', sa.Date(), nullable=False),
    sa.Column('expected_delivery_date', sa.Date(), nullable=True),
    sa.Column('customer_id', sa.Integer(), nullable=False),
    sa.Column('customer_name', sa.String(length=200), nullable=False),
    sa.Column('customer_tin', sa.String(length=20), nullable=True),
    sa.Column('customer_address', sa.Text(), nullable=True),
    sa.Column('customer_po_number', sa.String(length=100), nullable=True),
    sa.Column('customer_po_date', sa.Date(), nullable=True),
    sa.Column('payment_terms', sa.String(length=50), nullable=True),
    sa.Column('reference', sa.String(length=100), nullable=True),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('subtotal', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('vat_amount', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('vat_override', sa.Boolean(), nullable=False),
    sa.Column('total_amount', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('sales_invoice_id', sa.Integer(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('confirmed_by_id', sa.Integer(), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(), nullable=True),
    sa.Column('cancelled_by_id', sa.Integer(), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(), nullable=True),
    sa.Column('cancel_reason', sa.String(length=500), nullable=True),
    sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], ),
    sa.ForeignKeyConstraint(['cancelled_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['confirmed_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
    sa.ForeignKeyConstraint(['sales_invoice_id'], ['sales_invoices.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('sales_orders', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sales_orders_branch_id'), ['branch_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_sales_orders_customer_id'), ['customer_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_sales_orders_order_date'), ['order_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_sales_orders_so_number'), ['so_number'], unique=True)
        batch_op.create_index(batch_op.f('ix_sales_orders_status'), ['status'], unique=False)

    op.create_table('sales_order_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sales_order_id', sa.Integer(), nullable=False),
    sa.Column('line_number', sa.Integer(), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=False),
    sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=15, scale=4), nullable=True),
    sa.Column('unit_price', sa.Numeric(precision=15, scale=2), nullable=True),
    sa.Column('uom_text', sa.String(length=20), nullable=True),
    sa.Column('unit_of_measure_id', sa.Integer(), nullable=True),
    sa.Column('product_id', sa.Integer(), nullable=True),
    sa.Column('vat_category', sa.String(length=100), nullable=True),
    sa.Column('vat_rate', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('line_total', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('vat_amount', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.ForeignKeyConstraint(['sales_order_id'], ['sales_orders.id'], ),
    sa.ForeignKeyConstraint(['unit_of_measure_id'], ['units_of_measure.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('sales_order_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sales_order_items_sales_order_id'), ['sales_order_id'], unique=False)


def downgrade():
    with op.batch_alter_table('sales_order_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sales_order_items_sales_order_id'))

    op.drop_table('sales_order_items')

    with op.batch_alter_table('sales_orders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sales_orders_status'))
        batch_op.drop_index(batch_op.f('ix_sales_orders_so_number'))
        batch_op.drop_index(batch_op.f('ix_sales_orders_order_date'))
        batch_op.drop_index(batch_op.f('ix_sales_orders_customer_id'))
        batch_op.drop_index(batch_op.f('ix_sales_orders_branch_id'))

    op.drop_table('sales_orders')
