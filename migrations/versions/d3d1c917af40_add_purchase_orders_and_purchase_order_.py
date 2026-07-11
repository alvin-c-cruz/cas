"""add purchase_orders and purchase_order_items

Revision ID: d3d1c917af40
Revises: d1e2f3a4b5c6
Create Date: 2026-07-11 17:17:40.838774

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd3d1c917af40'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade():
    # purchase_orders header. Mixes RowVersioned -> row_version column is REQUIRED here
    # (it is NOT added by the shared 7f2b9c31ad04 backfill, which only covered the headers
    # that existed then). purchase_request_id is a bare Integer (no FK) on purpose -- mirror of
    # SalesOrder.quotation_id, avoids the metadata cycle / unnamed-constraint trap.
    op.create_table('purchase_orders',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=True),
        sa.Column('po_number', sa.String(length=50), nullable=False),
        sa.Column('order_date', sa.Date(), nullable=True),
        sa.Column('expected_date', sa.Date(), nullable=True),
        sa.Column('vendor_id', sa.Integer(), sa.ForeignKey('vendors.id'), nullable=True),
        sa.Column('vendor_name', sa.String(length=200), nullable=True),
        sa.Column('vendor_tin', sa.String(length=30), nullable=True),
        sa.Column('vendor_address', sa.String(length=300), nullable=True),
        sa.Column('payment_terms', sa.String(length=50), nullable=True),
        sa.Column('reference', sa.String(length=100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('vat_treatment', sa.String(length=10), nullable=False, server_default='inclusive'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('purchase_request_id', sa.Integer(), nullable=True),          # bare Integer, no FK
        sa.Column('accounts_payable_id', sa.Integer(), sa.ForeignKey('accounts_payable.id'), nullable=True),
        sa.Column('subtotal', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'),
        sa.Column('vat_amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'),
        sa.Column('vat_override', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('total_amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('cancel_reason', sa.String(length=500), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
    )
    with op.batch_alter_table('purchase_orders', schema=None) as b:
        b.create_index('ix_purchase_orders_po_number', ['po_number'], unique=True)
        b.create_index('ix_purchase_orders_branch_id', ['branch_id'])
        b.create_index('ix_purchase_orders_vendor_id', ['vendor_id'])
        b.create_index('ix_purchase_orders_order_date', ['order_date'])
        b.create_index('ix_purchase_orders_status', ['status'])
        b.create_index('ix_purchase_orders_purchase_request_id', ['purchase_request_id'])

    op.create_table('purchase_order_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('purchase_order_id', sa.Integer(), sa.ForeignKey('purchase_orders.id'), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'),
        sa.Column('quantity', sa.Numeric(precision=15, scale=4), nullable=True),
        sa.Column('unit_price', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('uom_text', sa.String(length=20), nullable=True),
        sa.Column('unit_of_measure_id', sa.Integer(), sa.ForeignKey('units_of_measure.id'), nullable=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=True),
        sa.Column('vat_category', sa.String(length=100), nullable=True),
        sa.Column('vat_rate', sa.Numeric(precision=5, scale=2), nullable=False, server_default='0'),
        sa.Column('line_total', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'),
        sa.Column('vat_amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'),
        sa.Column('received_quantity', sa.Numeric(precision=15, scale=4), nullable=True, server_default='0'),
        sa.Column('billed_quantity', sa.Numeric(precision=15, scale=4), nullable=True, server_default='0'),
    )
    with op.batch_alter_table('purchase_order_items', schema=None) as b:
        b.create_index('ix_purchase_order_items_purchase_order_id', ['purchase_order_id'])


def downgrade():
    op.drop_table('purchase_order_items')
    op.drop_table('purchase_orders')
