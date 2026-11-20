"""RIC's pre-printed forms: SI "SO No." and Delivery Address, PO "Requested by" (RICL-4a / 4e / 4d)

Owner, 17 Nov 2026 (work order 2026-11-13-ric-preprinted-print-layouts, letters relayed word for word):
  * 4a, SI "SO No.": "If SO is activated then this can be the source. If not, the user can type the SO." The print takes
    the sales orders behind the DRs the invoice bills, else this typed `sales_invoices.so_number`.
  * 4e, a typed `sales_invoices.delivery_address`, started from the SO line's delivery site when the SI is pulled from
    a DR.
  * 4d, `purchase_orders.requested_by`, pre-filled from the requisition's Prepared by (else its creator), editable.
Three nullable columns; every existing document starts NULL and prints as before.

Revision ID: riclay_0001
Revises: cdvslip_0001
Create Date: 2026-11-19
"""
import sqlalchemy as sa
from alembic import op

revision = 'riclay_0001'
down_revision = 'cdvslip_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('sales_invoices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('so_number', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('delivery_address', sa.Text(), nullable=True))
    with op.batch_alter_table('purchase_orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('requested_by', sa.String(length=100), nullable=True))


def downgrade():
    with op.batch_alter_table('purchase_orders', schema=None) as batch_op:
        batch_op.drop_column('requested_by')
    with op.batch_alter_table('sales_invoices', schema=None) as batch_op:
        batch_op.drop_column('delivery_address')
        batch_op.drop_column('so_number')
