"""add quotations and quotation_id on sales_orders

Revision ID: 29500ade76f8
Revises: b3d7f1c04e28
Create Date: 2026-07-09 22:20:41.867133

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '29500ade76f8'
down_revision = 'b3d7f1c04e28'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('quotations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=True),
        sa.Column('quotation_number', sa.String(length=50), nullable=False),
        sa.Column('quotation_date', sa.Date(), nullable=False),
        sa.Column('valid_until', sa.Date(), nullable=True),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id'), nullable=False),
        sa.Column('customer_name', sa.String(length=200), nullable=False),
        sa.Column('customer_tin', sa.String(length=20), nullable=True),
        sa.Column('customer_address', sa.Text(), nullable=True),
        sa.Column('payment_terms', sa.String(length=50), nullable=True),
        sa.Column('reference', sa.String(length=100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('vat_treatment', sa.String(length=10), nullable=False, server_default='inclusive'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('salesperson_id', sa.Integer(), sa.ForeignKey('employees.id'), nullable=True),
        sa.Column('sales_order_id', sa.Integer(), sa.ForeignKey('sales_orders.id'), nullable=True),
        sa.Column('subtotal', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0.00'),
        sa.Column('vat_amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0.00'),
        sa.Column('total_amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0.00'),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('sent_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('accepted_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('accepted_at', sa.DateTime(), nullable=True),
        sa.Column('rejected_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('rejected_at', sa.DateTime(), nullable=True),
        sa.Column('reject_reason', sa.String(length=500), nullable=True),
        sa.Column('cancelled_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('cancel_reason', sa.String(length=500), nullable=True),
    )
    with op.batch_alter_table('quotations', schema=None) as b:
        b.create_index('ix_quotations_quotation_number', ['quotation_number'], unique=True)
        b.create_index('ix_quotations_branch_id', ['branch_id'])
        b.create_index('ix_quotations_quotation_date', ['quotation_date'])
        b.create_index('ix_quotations_customer_id', ['customer_id'])
        b.create_index('ix_quotations_status', ['status'])
        b.create_index('ix_quotations_salesperson_id', ['salesperson_id'])
        b.create_index('ix_quotations_sales_order_id', ['sales_order_id'])

    op.create_table('quotation_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('quotation_id', sa.Integer(), sa.ForeignKey('quotations.id'), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0.00'),
        sa.Column('quantity', sa.Numeric(precision=15, scale=4), nullable=True),
        sa.Column('unit_price', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('uom_text', sa.String(length=20), nullable=True),
        sa.Column('unit_of_measure_id', sa.Integer(), sa.ForeignKey('units_of_measure.id'), nullable=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=True),
        sa.Column('vat_category', sa.String(length=100), nullable=True),
        sa.Column('vat_rate', sa.Numeric(precision=5, scale=2), nullable=False, server_default='0.00'),
        sa.Column('line_total', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0.00'),
        sa.Column('vat_amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0.00'),
    )
    with op.batch_alter_table('quotation_items', schema=None) as b:
        b.create_index('ix_quotation_items_quotation_id', ['quotation_id'])

    # Add the FK column as a plain Integer (no inline FK constraint): batch mode cannot name the
    # constraint, and SQLite FK enforcement is off app-wide. The ORM model still declares the FK
    # for the relationship. Mirrors the salesperson_id migration (e95cdff4e8e6).
    with op.batch_alter_table('sales_orders', schema=None) as b:
        b.add_column(sa.Column('quotation_id', sa.Integer(), nullable=True))
        b.create_index('ix_sales_orders_quotation_id', ['quotation_id'])


def downgrade():
    with op.batch_alter_table('sales_orders', schema=None) as b:
        b.drop_index('ix_sales_orders_quotation_id')
        b.drop_column('quotation_id')
    op.drop_table('quotation_items')
    op.drop_table('quotations')
