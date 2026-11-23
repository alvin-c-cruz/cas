"""Every delivery receipt keeps its own Customer PO (B2 A)

Owner, typed in the root 23 Nov 2026: "B2 A" -- a Customer PO field on every DR. Against an order it starts as the
order's PO and can be changed; without one it is typed in. The DR page, both DR prints and the invoice's DR billing read
the DR's own PO from now on (until now the pre-printed print and the billing read the order's).

So every existing DR against an order takes its order's PO here and prints as before. A DR without an order, or whose
order has no PO (NULL or blank), stays NULL.

Revision ID: drpo_0001
Revises: riclay_0001
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op

revision = 'drpo_0001'
down_revision = 'riclay_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('delivery_receipts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('customer_po_number', sa.String(length=100), nullable=True))
    op.execute(
        'UPDATE delivery_receipts SET customer_po_number = '
        "(SELECT NULLIF(TRIM(sales_orders.customer_po_number), '') FROM sales_orders "
        ' WHERE sales_orders.id = delivery_receipts.sales_order_id) '
        'WHERE sales_order_id IS NOT NULL')


def downgrade():
    with op.batch_alter_table('delivery_receipts', schema=None) as batch_op:
        batch_op.drop_column('customer_po_number')
