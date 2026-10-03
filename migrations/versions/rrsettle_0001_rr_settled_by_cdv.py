"""a receiving report can be settled by a cash disbursement voucher, outside AP

Owner, 2026-10-03: the AP module started in September, so a receipt paid in August by a
legacy cash voucher can never be billed -- it would sit 'approved, unbilled' for good.
An administrator may now close such a receipt against the CDV that paid it.

  receiving_reports.settled_cdv_id / settled_by_id / settled_at / settle_reason

All four nullable and additive. Nothing to backfill: every existing row reads NULL and
behaves exactly as it does today.

settled_cdv_id and settled_by_id are PLAIN INTEGERS here with db.ForeignKey on the ORM
side only -- a SQLite batch add_column cannot carry an inline foreign key ("Constraint
must have a name" during the table rebuild). Same arrangement as rrreason_0001.

Revision ID: rrsettle_0001
Revises: soatt_0001
Create Date: 2026-10-03

"""
from alembic import op
import sqlalchemy as sa


revision = 'rrsettle_0001'
down_revision = 'soatt_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('receiving_reports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('settled_cdv_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('settled_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('settled_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('settle_reason', sa.Text(), nullable=True))
        batch_op.create_index('ix_receiving_reports_settled_cdv_id', ['settled_cdv_id'])


def downgrade():
    """Drops the columns.

    A receipt settled before the downgrade keeps status 'billed' with nothing saying why,
    so reopen every settled receipt (back to 'approved') before running this.
    """
    with op.batch_alter_table('receiving_reports', schema=None) as batch_op:
        batch_op.drop_index('ix_receiving_reports_settled_cdv_id')
        batch_op.drop_column('settle_reason')
        batch_op.drop_column('settled_at')
        batch_op.drop_column('settled_by_id')
        batch_op.drop_column('settled_cdv_id')
