"""add receiving_reports and receiving_report_items

Revision ID: b23c5eed9612
Revises: d3d1c917af40
Create Date: 2026-07-11 18:14:56.377117

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b23c5eed9612'
down_revision = 'd3d1c917af40'
branch_labels = None
depends_on = None


def upgrade():
    # receiving_reports header. Mixes RowVersioned -> row_version REQUIRED here.
    # journal_entry_id is an inert accrual seam (deferred GRNI); accounts_payable_id is the
    # Phase-3 billing seam. Both nullable FKs declared inline (create_table allows inline FKs).
    op.create_table('receiving_reports',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=True),
        sa.Column('rr_number', sa.String(length=50), nullable=False),
        sa.Column('receipt_date', sa.Date(), nullable=False),
        sa.Column('purchase_order_id', sa.Integer(), sa.ForeignKey('purchase_orders.id'), nullable=False),
        sa.Column('vendor_id', sa.Integer(), sa.ForeignKey('vendors.id'), nullable=True),
        sa.Column('vendor_name', sa.String(length=200), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('accounts_payable_id', sa.Integer(), sa.ForeignKey('accounts_payable.id'), nullable=True),
        sa.Column('journal_entry_id', sa.Integer(), sa.ForeignKey('journal_entries.id'), nullable=True),
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
    with op.batch_alter_table('receiving_reports', schema=None) as b:
        b.create_index('ix_receiving_reports_rr_number', ['rr_number'], unique=True)
        b.create_index('ix_receiving_reports_branch_id', ['branch_id'])
        b.create_index('ix_receiving_reports_purchase_order_id', ['purchase_order_id'])
        b.create_index('ix_receiving_reports_vendor_id', ['vendor_id'])
        b.create_index('ix_receiving_reports_receipt_date', ['receipt_date'])
        b.create_index('ix_receiving_reports_status', ['status'])
        b.create_index('ix_receiving_reports_accounts_payable_id', ['accounts_payable_id'])

    op.create_table('receiving_report_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('receiving_report_id', sa.Integer(), sa.ForeignKey('receiving_reports.id'), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('purchase_order_item_id', sa.Integer(), sa.ForeignKey('purchase_order_items.id'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=True),
        sa.Column('received_quantity', sa.Numeric(precision=15, scale=4), nullable=False),
    )
    with op.batch_alter_table('receiving_report_items', schema=None) as b:
        b.create_index('ix_receiving_report_items_receiving_report_id', ['receiving_report_id'])
        b.create_index('ix_receiving_report_items_purchase_order_item_id', ['purchase_order_item_id'])


def downgrade():
    op.drop_table('receiving_report_items')
    op.drop_table('receiving_reports')
