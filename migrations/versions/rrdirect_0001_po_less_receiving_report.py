"""receiving_report_items.purchase_order_item_id becomes nullable (PO-less receipts)

A receiving report could only ever record goods arriving against a purchase order.
Deliveries that arrive without one -- a walk-in purchase, a replacement part, a
sample -- had nowhere to be recorded (owner request, 2026-09-06).

The column stays a real FK; it simply stops being mandatory. A line with it NULL is
a DIRECT receipt: its product, description and unit of measure come from
`product_id` (already on this table) instead of from the order line, and its cost
comes from the product master -- Product.standard_cost, else the branch's running
StockBalance.average_unit_cost. A receiving report never carries a unit price
(owner: "RR cannot have unit price"); the receiver records what arrived, not what
it costs.

DATA: nothing to backfill. Every existing row has a purchase_order_item_id because
the column was NOT NULL, and they keep it -- this only permits new rows without one.

SQLite has no ALTER COLUMN, so this is a batch rebuild: Alembic recreates the table
and copies the rows. The rebuild reflects the existing foreign keys, which on this
table are UNNAMED (they were declared inline in the original create_table). That is
the exact hazard the workspace conventions warn about, so this migration was run
against a COPY OF THE LIVE PHILGEN DATABASE before being committed -- not against a
create_all() test database, which builds its schema from the models and so cannot
reproduce the real one's constraint naming.

Revision ID: rrdirect_0001
Revises: prreturn_0001
Create Date: 2026-09-06

"""
from alembic import op
import sqlalchemy as sa


revision = 'rrdirect_0001'
down_revision = 'prreturn_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('receiving_report_items', schema=None) as batch_op:
        batch_op.alter_column('purchase_order_item_id',
                              existing_type=sa.Integer(),
                              nullable=True)


def downgrade():
    """Refuses rather than destroys.

    Going back means the column is NOT NULL again, and any direct receipt recorded
    meanwhile has no order line to point at. Deleting those rows would silently
    destroy posted receipts -- and their stock movements and GRNI journal entries
    would survive, leaving the ledger referring to receipt lines that no longer
    exist. Better to stop and make the operator decide what should happen to them.
    """
    conn = op.get_bind()
    orphans = conn.execute(sa.text(
        'SELECT COUNT(*) FROM receiving_report_items '
        'WHERE purchase_order_item_id IS NULL')).scalar()
    if orphans:
        raise RuntimeError(
            '%d receiving report line(s) were recorded without a purchase order. '
            'Downgrading would make the column NOT NULL again with nowhere to put '
            'them. Reassign or delete those lines deliberately, then retry.' % orphans)
    with op.batch_alter_table('receiving_report_items', schema=None) as batch_op:
        batch_op.alter_column('purchase_order_item_id',
                              existing_type=sa.Integer(),
                              nullable=False)
