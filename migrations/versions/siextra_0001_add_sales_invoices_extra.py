"""add sales_invoices_extra and sales_invoice_extra_items

Revision ID: siextra_0001
Revises: custvc_0001
Create Date: 2026-07-30 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'siextra_0001'
down_revision = 'custvc_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'sales_invoices_extra',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('branch_id', sa.Integer(), nullable=False),
        sa.Column('invoice_number', sa.String(length=50), nullable=False),
        sa.Column('invoice_date', sa.Date(), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('customer_name', sa.String(length=200), nullable=False),
        sa.Column('customer_address', sa.Text(), nullable=True),
        sa.Column('payment_terms', sa.String(length=50), nullable=True),
        sa.Column('reference', sa.String(length=100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('delivery_receipt_id', sa.Integer(), nullable=True),
        sa.Column('subtotal', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('total_amount', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('ar_trade_account_id', sa.Integer(), nullable=True),
        sa.Column('sales_revenue_account_id', sa.Integer(), nullable=True),
        sa.Column('is_cash_sale', sa.Boolean(), nullable=False),
        sa.Column('cash_account_id', sa.Integer(), nullable=True),
        sa.Column('journal_entry_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('amount_paid', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('balance', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('salesperson_id', sa.Integer(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('posted_by_id', sa.Integer(), nullable=True),
        sa.Column('voided_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('posted_at', sa.DateTime(), nullable=True),
        sa.Column('voided_at', sa.DateTime(), nullable=True),
        sa.Column('void_reason', sa.String(length=255), nullable=True),
        sa.Column('cancel_reason', sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], name='fk_sie_branch'),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name='fk_sie_customer'),
        sa.ForeignKeyConstraint(['delivery_receipt_id'], ['delivery_receipts.id'], name='fk_sie_dr'),
        sa.ForeignKeyConstraint(['ar_trade_account_id'], ['accounts.id'], name='fk_sie_ar_account'),
        sa.ForeignKeyConstraint(['sales_revenue_account_id'], ['accounts.id'], name='fk_sie_revenue_account'),
        sa.ForeignKeyConstraint(['cash_account_id'], ['accounts.id'], name='fk_sie_cash_account'),
        sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entries.id'], name='fk_sie_je'),
        sa.ForeignKeyConstraint(['salesperson_id'], ['employees.id'], name='fk_sie_salesperson'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name='fk_sie_created_by'),
        sa.ForeignKeyConstraint(['posted_by_id'], ['users.id'], name='fk_sie_posted_by'),
        sa.ForeignKeyConstraint(['voided_by_id'], ['users.id'], name='fk_sie_voided_by'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('invoice_number', name='uq_sie_invoice_number'),
        sa.UniqueConstraint('delivery_receipt_id', name='uq_sie_delivery_receipt'),
    )
    with op.batch_alter_table('sales_invoices_extra', schema=None) as batch_op:
        batch_op.create_index('ix_sie_branch_id', ['branch_id'])
        batch_op.create_index('ix_sie_customer_id', ['customer_id'])
        batch_op.create_index('ix_sie_invoice_date', ['invoice_date'])
        batch_op.create_index('ix_sie_invoice_number', ['invoice_number'])
        batch_op.create_index('ix_sie_salesperson_id', ['salesperson_id'])
        batch_op.create_index('ix_sie_status', ['status'])

    op.create_table(
        'sales_invoice_extra_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=True),
        sa.Column('quantity', sa.Numeric(precision=15, scale=4), nullable=True),
        sa.Column('unit_price', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('uom_text', sa.String(length=20), nullable=True),
        sa.Column('unit_of_measure_id', sa.Integer(), nullable=True),
        sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.ForeignKeyConstraint(['invoice_id'], ['sales_invoices_extra.id'], name='fk_siei_invoice'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], name='fk_siei_product'),
        sa.ForeignKeyConstraint(['unit_of_measure_id'], ['units_of_measure.id'], name='fk_siei_uom'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('sales_invoice_extra_items', schema=None) as batch_op:
        batch_op.create_index('ix_siei_invoice_id', ['invoice_id'])


def downgrade():
    with op.batch_alter_table('sales_invoice_extra_items', schema=None) as batch_op:
        batch_op.drop_index('ix_siei_invoice_id')
    op.drop_table('sales_invoice_extra_items')

    with op.batch_alter_table('sales_invoices_extra', schema=None) as batch_op:
        batch_op.drop_index('ix_sie_status')
        batch_op.drop_index('ix_sie_salesperson_id')
        batch_op.drop_index('ix_sie_invoice_number')
        batch_op.drop_index('ix_sie_invoice_date')
        batch_op.drop_index('ix_sie_customer_id')
        batch_op.drop_index('ix_sie_branch_id')
    op.drop_table('sales_invoices_extra')
