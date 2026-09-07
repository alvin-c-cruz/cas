"""receiving_report_items.unit_of_measure_id -- the unit a DIRECT receipt arrived in

A PO-backed line takes its unit from the order line. A direct receipt (rrdirect_0001)
has no order line, so until now it fell back to the product's default unit -- which is
often right and sometimes not: goods can arrive by the box when the product is carried
by the piece, and a product may have no default unit at all. The receiver knows what
turned up, so let them say (owner, 2026-09-07).

Additive and nullable. Every existing row has NULL and keeps deriving its unit exactly as
before -- from the order line, or from the product. Nothing to backfill.

FK DECLARED ON THE ORM SIDE ONLY, not here. A SQLite batch add_column cannot carry an
inline sa.ForeignKey: the table rebuild raises "Constraint must have a name". So this is
a plain Integer column and app/receiving_reports/models.py holds the db.ForeignKey. Same
arrangement as employee_loans (3c4d5e6f7a8b) and, on this very table, stock_movement_id
-- which is why receiving_report_items shows three foreign keys in the live database and
not four.

Revision ID: rruom_0001
Revises: rrdirect_0001
Create Date: 2026-09-07

"""
from alembic import op
import sqlalchemy as sa


revision = 'rruom_0001'
down_revision = 'rrdirect_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('receiving_report_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('unit_of_measure_id', sa.Integer(), nullable=True))


def downgrade():
    """Drops the column, and with it any unit a receiver chose for a direct line.

    Safe to lose: the line still resolves a unit afterwards (order line, else the
    product's default), so a downgraded database reads consistently rather than showing
    blanks. Only the receiver's override is gone.
    """
    with op.batch_alter_table('receiving_report_items', schema=None) as batch_op:
        batch_op.drop_column('unit_of_measure_id')
