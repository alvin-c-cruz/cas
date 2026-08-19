"""Receiving Report: a submit step before approval

Revision ID: rrsub_0001
Revises: posig_0001
Create Date: 2026-08-19

A receipt went draft -> approved directly, and approve is accountant-or-above,
so the staff receiver who actually counted the goods could record it and then
move it nowhere. The new draft -> submitted -> approved chain mirrors the
Purchase Requisition's and the Purchase Order's.

Both columns are nullable with no backfill: an existing receipt was never
submitted, which is exactly true of it. Nothing is dropped and no existing value
is rewritten, so this is reversible without loss.

submitted_by_id is added as a bare Integer -- SQLite batch mode cannot emit an
unnamed FOREIGN KEY inside a table rebuild ("Constraint must have a name"), and
FK enforcement is off app-wide, so the ORM-side db.ForeignKey is what matters.

The 'submitted' status itself needs no migration: status is a String column with
no CHECK constraint, and COMMITTED_STATUSES ('approved', 'billed') deliberately
does NOT include it -- a submitted receipt has not yet committed stock, so it
must not count against a purchase order line's open quantity.
"""
import sqlalchemy as sa
from alembic import op

revision = 'rrsub_0001'
down_revision = 'posig_0001'
branch_labels = None
depends_on = None


NEW_COLUMNS = (
    ('submitted_by_id', sa.Integer()),
    ('submitted_at', sa.DateTime()),
)


def upgrade():
    existing = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('receiving_reports')}
    with op.batch_alter_table('receiving_reports') as batch:
        for name, type_ in NEW_COLUMNS:
            if name not in existing:
                batch.add_column(sa.Column(name, type_, nullable=True))


def downgrade():
    existing = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('receiving_reports')}
    with op.batch_alter_table('receiving_reports') as batch:
        for name, _ in reversed(NEW_COLUMNS):
            if name in existing:
                batch.drop_column(name)
