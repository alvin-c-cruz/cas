"""add purchase_memos and purchase_memo_items (Vendor Debit/Credit memo)

Revision ID: c4f8e1a9d5b7
Revises: e26366f5addf
Create Date: 2026-07-16 00:00:00.000000

Two new tables only -- no changes to any existing table. Real inline FKs are safe
here (fresh create_table, no metadata cycle); the batch-add-column FK trap
(SQLite batch mode "Constraint must have a name") only applies to
op.batch_alter_table(...).add_column on EXISTING tables. Mirrors
a7c3f1e9b2d4_add_sales_memos.py exactly, buy-side field names.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4f8e1a9d5b7'
down_revision = 'e26366f5addf'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('purchase_memos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=True),
        sa.Column('memo_type', sa.String(length=10), nullable=False),
        sa.Column('memo_number', sa.String(length=50), nullable=False),
        sa.Column('memo_date', sa.Date(), nullable=False),
        sa.Column('accounts_payable_id', sa.Integer(), sa.ForeignKey('accounts_payable.id'), nullable=False),
        sa.Column('original_ap_number', sa.String(length=50), nullable=False),
        sa.Column('vendor_id', sa.Integer(), sa.ForeignKey('vendors.id'), nullable=False),
        sa.Column('vendor_name', sa.String(length=200), nullable=False),
        sa.Column('vendor_tin', sa.String(length=20), nullable=True),
        sa.Column('vendor_address', sa.Text(), nullable=True),
        sa.Column('reason', sa.String(length=500), nullable=False),
        sa.Column('reference', sa.String(length=100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('subtotal', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0.00'),
        sa.Column('vat_amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0.00'),
        sa.Column('withholding_tax_amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0.00'),
        sa.Column('total_amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0.00'),
        sa.Column('destination', sa.String(length=20), nullable=False, server_default='ap'),
        sa.Column('cash_account_id', sa.Integer(), sa.ForeignKey('accounts.id'), nullable=True),
        sa.Column('journal_entry_id', sa.Integer(), sa.ForeignKey('journal_entries.id'), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('posted_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('voided_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('posted_at', sa.DateTime(), nullable=True),
        sa.Column('voided_at', sa.DateTime(), nullable=True),
        sa.Column('void_reason', sa.String(length=255), nullable=True),
    )
    with op.batch_alter_table('purchase_memos', schema=None) as b:
        b.create_index('ix_purchase_memos_memo_number', ['memo_number'], unique=True)
        b.create_index('ix_purchase_memos_memo_type', ['memo_type'])
        b.create_index('ix_purchase_memos_branch_id', ['branch_id'])
        b.create_index('ix_purchase_memos_memo_date', ['memo_date'])
        b.create_index('ix_purchase_memos_accounts_payable_id', ['accounts_payable_id'])
        b.create_index('ix_purchase_memos_vendor_id', ['vendor_id'])
        b.create_index('ix_purchase_memos_status', ['status'])

    op.create_table('purchase_memo_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('purchase_memo_id', sa.Integer(), sa.ForeignKey('purchase_memos.id'), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('accounts_payable_item_id', sa.Integer(), sa.ForeignKey('accounts_payable_items.id'), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=15, scale=4), nullable=True),
        sa.Column('unit_price', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('uom_text', sa.String(length=20), nullable=True),
        sa.Column('unit_of_measure_id', sa.Integer(), sa.ForeignKey('units_of_measure.id'), nullable=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=True),
        sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0.00'),
        sa.Column('line_total', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0.00'),
        sa.Column('vat_category', sa.String(length=100), nullable=True),
        sa.Column('vat_rate', sa.Numeric(precision=5, scale=2), nullable=False, server_default='0.00'),
        sa.Column('vat_amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0.00'),
        sa.Column('wt_id', sa.Integer(), sa.ForeignKey('withholding_tax.id'), nullable=True),
        sa.Column('wt_rate', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('wt_amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0.00'),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('accounts.id'), nullable=True),
    )
    with op.batch_alter_table('purchase_memo_items', schema=None) as b:
        b.create_index('ix_purchase_memo_items_purchase_memo_id', ['purchase_memo_id'])
        b.create_index('ix_purchase_memo_items_accounts_payable_item_id', ['accounts_payable_item_id'])


def downgrade():
    op.drop_table('purchase_memo_items')
    op.drop_table('purchase_memos')
