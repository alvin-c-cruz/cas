"""return-to-draft memo on a receiving report, and a no-PO override reason on its lines

Two additions from one design (docs/design/2026-09-07-rr-po-found-after-submit-design.md):

  receiving_reports.return_reason / returned_by_id / returned_at
      A submitted receipt can be sent back to draft when the purchase order that
      covered the goods turns up afterwards. The memo says why.

  receiving_report_items.no_po_reason
      A direct line whose product HAS an open order line for the same vendor is
      flagged at entry. If the receiver says it genuinely had no order, that
      judgement is recorded here rather than lost.

All four nullable and additive. Nothing to backfill: every existing row reads NULL and
behaves exactly as it does today.

returned_by_id is a PLAIN INTEGER here with db.ForeignKey on the ORM side only -- a
SQLite batch add_column cannot carry an inline foreign key ("Constraint must have a
name" during the table rebuild). Same arrangement prreturn_0001 used, and the reason
receiving_report_items shows three foreign keys in the live database rather than five.

Revision ID: rrreason_0001
Revises: rruom_0001
Create Date: 2026-09-07

"""
from alembic import op
import sqlalchemy as sa


revision = 'rrreason_0001'
down_revision = 'rruom_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('receiving_reports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('return_reason', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('returned_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('returned_at', sa.DateTime(), nullable=True))
    with op.batch_alter_table('receiving_report_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('no_po_reason', sa.Text(), nullable=True))


def downgrade():
    """Drops the columns and the memos in them.

    Safe: nothing derives from these. A downgraded database loses the record of WHY a
    receipt was returned or why a line was kept without an order, but every receipt and
    line still reads correctly. The audit log keeps both texts regardless.
    """
    with op.batch_alter_table('receiving_report_items', schema=None) as batch_op:
        batch_op.drop_column('no_po_reason')
    with op.batch_alter_table('receiving_reports', schema=None) as batch_op:
        batch_op.drop_column('returned_at')
        batch_op.drop_column('returned_by_id')
        batch_op.drop_column('return_reason')
