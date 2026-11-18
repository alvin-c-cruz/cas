"""A delivery receipt may have no sales order (DR-NOSO)

Owner, 17 Nov 2026: "right now DR must have an SO. but some DR need no SO"; DR-NOSO "A (my pick)": a "No sales
order" choice on the DR form, on every branch. delivery_receipts.sales_order_id and
delivery_receipt_items.sales_order_item_id become nullable; a DR line gets its own unit (own_unit_of_measure_id) for
lines with no SO line to take it from. Existing rows are untouched.

Revision ID: drnoso_0001
Revises: pwforce_0001   (if cdvslip_0001 is merged first, re-point this to cdvslip_0001 -- one line)
Create Date: 2026-11-17
"""
import sqlalchemy as sa
from alembic import op

revision = 'drnoso_0001'
down_revision = 'pwforce_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('delivery_receipts', schema=None) as batch_op:
        batch_op.alter_column('sales_order_id', existing_type=sa.Integer(), nullable=True)
    with op.batch_alter_table('delivery_receipt_items', schema=None) as batch_op:
        batch_op.alter_column('sales_order_item_id', existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column('own_unit_of_measure_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('delivery_receipt_items', schema=None) as batch_op:
        batch_op.drop_column('own_unit_of_measure_id')
        batch_op.alter_column('sales_order_item_id', existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table('delivery_receipts', schema=None) as batch_op:
        batch_op.alter_column('sales_order_id', existing_type=sa.Integer(), nullable=False)
