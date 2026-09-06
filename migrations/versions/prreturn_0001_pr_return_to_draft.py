"""Purchase Requisition: return to draft, with a memo saying why.

Adds the provenance for a NEW transition -- a requisition going BACK to draft --
alongside the existing submit/approve/reject/cancel columns. Two source states
reach it (owner request 2026-09-06):

  submitted -> draft   the approver's third choice beside Approve and Reject:
                       send it back to be fixed rather than refuse it outright.
  rejected  -> draft   recovery from a decision already made, e.g. the number
                       must follow the client's old manual sequence.

Purely ADDITIVE -- three nullable columns on one existing table. Nothing about an
existing requisition changes, so a client that never uses the feature is
byte-identical afterwards, and every rejected_* / cancelled_* value is left
exactly where it is: returning a requisition does not erase the decision it
reverses, so the detail page can show the whole arc.

`returned_by_id` is a PLAIN Integer with NO inline sa.ForeignKey: a batch
add_column cannot carry one (SQLite batch mode raises "Constraint must have a
name" during the table rebuild). The ORM side still declares db.ForeignKey, so
relationship joins are unaffected -- only the migration column is bare.

Revision ID: prreturn_0001
Revises: pocur_0001
"""
import sqlalchemy as sa
from alembic import op

revision = 'prreturn_0001'
down_revision = 'pocur_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('purchase_requests') as batch:
        batch.add_column(sa.Column('returned_by_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('returned_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('return_reason', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('purchase_requests') as batch:
        batch.drop_column('return_reason')
        batch.drop_column('returned_at')
        batch.drop_column('returned_by_id')
