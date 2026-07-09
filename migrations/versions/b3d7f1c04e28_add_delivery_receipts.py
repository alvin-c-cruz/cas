"""add delivery_receipts and delivery_receipt_items

Revision ID: b3d7f1c04e28
Revises: a84189785f23
Create Date: 2026-07-09 21:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3d7f1c04e28'
down_revision = 'a84189785f23'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('delivery_receipts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=True),
        sa.Column('dr_number', sa.String(length=50), nullable=False),
        sa.Column('delivery_date', sa.Date(), nullable=False),
        sa.Column('sales_order_id', sa.Integer(), sa.ForeignKey('sales_orders.id'), nullable=False),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id'), nullable=False),
        sa.Column('customer_name', sa.String(length=200), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('salesperson_id', sa.Integer(), sa.ForeignKey('employees.id'), nullable=True),
        sa.Column('sales_invoice_id', sa.Integer(), sa.ForeignKey('sales_invoices.id'), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('delivered_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('cancel_reason', sa.String(length=500), nullable=True),
    )
    with op.batch_alter_table('delivery_receipts', schema=None) as b:
        b.create_index('ix_delivery_receipts_dr_number', ['dr_number'], unique=True)
        b.create_index('ix_delivery_receipts_branch_id', ['branch_id'])
        b.create_index('ix_delivery_receipts_sales_order_id', ['sales_order_id'])
        b.create_index('ix_delivery_receipts_customer_id', ['customer_id'])
        b.create_index('ix_delivery_receipts_salesperson_id', ['salesperson_id'])
        b.create_index('ix_delivery_receipts_sales_invoice_id', ['sales_invoice_id'])
        b.create_index('ix_delivery_receipts_status', ['status'])
        b.create_index('ix_delivery_receipts_delivery_date', ['delivery_date'])

    op.create_table('delivery_receipt_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('delivery_receipt_id', sa.Integer(), sa.ForeignKey('delivery_receipts.id'), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('sales_order_item_id', sa.Integer(), sa.ForeignKey('sales_order_items.id'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=True),
        sa.Column('delivered_quantity', sa.Numeric(precision=15, scale=4), nullable=False),
    )
    with op.batch_alter_table('delivery_receipt_items', schema=None) as b:
        b.create_index('ix_delivery_receipt_items_delivery_receipt_id', ['delivery_receipt_id'])
        b.create_index('ix_delivery_receipt_items_sales_order_item_id', ['sales_order_item_id'])


def downgrade():
    op.drop_table('delivery_receipt_items')
    op.drop_table('delivery_receipts')
