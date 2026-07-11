"""add purchase_requests and purchase_request_items

Revision ID: be7db1227c52
Revises: b23c5eed9612
Create Date: 2026-07-11 18:57:55.454380

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'be7db1227c52'
down_revision = 'b23c5eed9612'
branch_labels = None
depends_on = None


def upgrade():
    # purchase_requests header. Mixes RowVersioned -> row_version REQUIRED here.
    # purchase_order_id is a real FK forward-link (mirror Quotation.sales_order_id); the reverse
    # PurchaseOrder.purchase_request_id is a bare Integer, so no metadata cycle.
    op.create_table('purchase_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=True),
        sa.Column('pr_number', sa.String(length=50), nullable=False),
        sa.Column('request_date', sa.Date(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('purchase_order_id', sa.Integer(), sa.ForeignKey('purchase_orders.id'), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('submitted_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('rejected_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('rejected_at', sa.DateTime(), nullable=True),
        sa.Column('reject_reason', sa.String(length=500), nullable=True),
        sa.Column('cancelled_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('cancel_reason', sa.String(length=500), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
    )
    with op.batch_alter_table('purchase_requests', schema=None) as b:
        b.create_index('ix_purchase_requests_pr_number', ['pr_number'], unique=True)
        b.create_index('ix_purchase_requests_branch_id', ['branch_id'])
        b.create_index('ix_purchase_requests_request_date', ['request_date'])
        b.create_index('ix_purchase_requests_status', ['status'])
        b.create_index('ix_purchase_requests_purchase_order_id', ['purchase_order_id'])

    op.create_table('purchase_request_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('purchase_request_id', sa.Integer(), sa.ForeignKey('purchase_requests.id'), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('quantity', sa.Numeric(precision=15, scale=4), nullable=True),
        sa.Column('uom_text', sa.String(length=20), nullable=True),
        sa.Column('unit_of_measure_id', sa.Integer(), sa.ForeignKey('units_of_measure.id'), nullable=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=True),
    )
    with op.batch_alter_table('purchase_request_items', schema=None) as b:
        b.create_index('ix_purchase_request_items_purchase_request_id', ['purchase_request_id'])


def downgrade():
    op.drop_table('purchase_request_items')
    op.drop_table('purchase_requests')
