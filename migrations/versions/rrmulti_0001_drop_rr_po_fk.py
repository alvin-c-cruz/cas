"""Receiving Report: drop the header purchase_order_id; vendor_id becomes the key

Revision ID: rrmulti_0001
Revises: stkdate_0001
Create Date: 2026-08-16

One receipt can settle several of ONE vendor's orders, so no single header FK can
be true. The PO link already lives on the line (`receiving_report_items
.purchase_order_item_id`, NOT NULL), and every reader was moved onto it earlier in
this branch -- `ReceivingReport.purchase_orders` derives the distinct set from the
lines. Nothing reads `receiving_reports.purchase_order_id` any more, so it goes,
and `vendor_id` -- the one thing that IS true of the whole header -- is tightened
to NOT NULL in its place.

Order of operations in upgrade():

1. Backfill `vendor_id` from the header PO BEFORE tightening it. Historically the
   column was populated from the PO at create, but it was only ever nullable, so a
   row written by an older build can hold NULL.
2. Refuse loudly, naming the receipts, if any row still has no vendor after the
   backfill. `purchase_orders.vendor_id` is itself nullable, so the subquery can
   return NULL. Without this the ALTER below fails with an opaque IntegrityError
   that names neither the table's real problem nor which rows caused it -- on a
   client's live database, mid-deploy.
3. Drop the column's index with a plain DROP INDEX before the batch block, rather
   than leaving it to the table rebuild to work out what to do with an index over
   a column that is going away.
4. Batch-rebuild: vendor_id -> NOT NULL, purchase_order_id dropped.

downgrade() re-adds the column as a plain `sa.Integer` -- a batch `add_column`
cannot carry an inline `sa.ForeignKey` ("Constraint must have a name"), and SQLite
FK enforcement is off app-wide, so the bare Integer loses nothing -- and
repopulates it from the FIRST line's purchase order (`ORDER BY line_number, id`),
which is what the create/edit views wrote while the column existed.

The re-added column is NULLABLE, where the original was NOT NULL. This is
deliberate and is the one place the round trip is not byte-exact: after this
upgrade a Receiving Report may legitimately carry NO lines (a fresh draft), and
such a row has no purchase order to name. Restoring NOT NULL would make downgrade
fail on data the upgraded schema explicitly allows -- a downgrade that cannot run
on the data its own upgrade permits is not a downgrade.
"""
import sqlalchemy as sa
from alembic import op

revision = 'rrmulti_0001'
down_revision = 'stkdate_0001'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    # 1. Backfill vendor_id from the header PO before tightening it.
    conn.execute(sa.text("""
        UPDATE receiving_reports
           SET vendor_id = (SELECT po.vendor_id FROM purchase_orders po
                             WHERE po.id = receiving_reports.purchase_order_id)
         WHERE vendor_id IS NULL"""))

    # 2. Refuse by name rather than letting the ALTER raise an opaque IntegrityError.
    orphans = conn.execute(sa.text(
        "SELECT rr_number FROM receiving_reports WHERE vendor_id IS NULL"
        " ORDER BY rr_number")).fetchall()
    if orphans:
        raise RuntimeError(
            'Cannot make receiving_reports.vendor_id NOT NULL: %d receipt(s) have no '
            'vendor and their header purchase order does not supply one either: %s. '
            'Set a vendor on those receipts (or on their purchase orders) and re-run.'
            % (len(orphans), ', '.join(str(r[0]) for r in orphans)))

    # 3. The index over the departing column, dropped explicitly.
    op.drop_index('ix_receiving_reports_purchase_order_id',
                  table_name='receiving_reports')

    # 4. Tighten the header key, drop the header FK.
    with op.batch_alter_table('receiving_reports') as b:
        b.alter_column('vendor_id', existing_type=sa.Integer(), nullable=False)
        b.drop_column('purchase_order_id')


def downgrade():
    """Restore the header column. THE ROUND TRIP IS NOT SCHEMA-EXACT, in three ways
    and one data way -- know them before rolling back:

    1. `purchase_order_id` comes back NULLABLE, not NOT NULL. After the upgrade a
       LINELESS receipt is legal and has no PO to name, so a NOT NULL restore would
       abort on data its own upgrade permits.
    2. It carries NO FOREIGN KEY to purchase_orders. A batch `add_column` cannot
       emit an unnamed FK ("Constraint must have a name"), and SQLite FK enforcement
       is off app-wide, so nothing is enforced either way -- but the restored schema
       is not byte-equal to the pre-upgrade one.
    3. It lands at the END of the column list, not at its original position 4.
       Nothing depends on column order here; noted so a schema diff does not read
       as a defect.
    4. DATA LOSS, unavoidable: a receipt drawing on SEVERAL purchase orders collapses
       to its FIRST line's PO alone, silently. That the header cannot represent a
       multi-PO receipt is the whole reason this column is being dropped, so a
       rollback cannot preserve what the old shape could not hold.
    """
    conn = op.get_bind()
    with op.batch_alter_table('receiving_reports') as b:
        # Plain Integer, no inline ForeignKey -- see the module docstring.
        b.add_column(sa.Column('purchase_order_id', sa.Integer(), nullable=True))
        b.alter_column('vendor_id', existing_type=sa.Integer(), nullable=True)

    # Repopulate from the FIRST line's purchase order, which is what create()/edit()
    # wrote while the column existed. A receipt with no lines keeps NULL.
    conn.execute(sa.text("""
        UPDATE receiving_reports
           SET purchase_order_id = (
                 SELECT poi.purchase_order_id
                   FROM receiving_report_items rri
                   JOIN purchase_order_items poi
                     ON poi.id = rri.purchase_order_item_id
                  WHERE rri.receiving_report_id = receiving_reports.id
                  ORDER BY rri.line_number, rri.id
                  LIMIT 1)"""))

    op.create_index('ix_receiving_reports_purchase_order_id',
                    'receiving_reports', ['purchase_order_id'])
