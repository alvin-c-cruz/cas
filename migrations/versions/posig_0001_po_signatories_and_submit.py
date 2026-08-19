"""Purchase Order: per-order signatories, and a submit step before approval

Revision ID: posig_0001
Revises: rrmulti_0001
Create Date: 2026-08-19

Five columns on purchase_orders, in ONE revision so a live client takes a single
schema change rather than two.

SIGNATORIES (prepared_by / checked_by / approved_by)
Per ORDER, not company-wide -- deliberately unlike the Purchase Requisition's and
Receiving Report's, which are AppSettings rows because the same three people sign
every one of those. This client runs two purchasers, each holding her own
pre-printed PO pad (see next_po_number_for), each routing orders past different
people, so a new PO pre-fills from that PURCHASER's own last order. Names match
the legacy Philgen form's fields verbatim.

SUBMIT (submitted_by_id / submitted_at)
A PO went draft -> approved directly, and approve is accountant-or-above, so a
staff purchaser could build an order and then move it nowhere. The new
draft -> submitted -> approved chain mirrors the requisition's.

All five are nullable with no backfill: an existing order simply has no
signatories recorded and was never submitted, which is exactly true of it. Nothing
is dropped and no existing value is rewritten, so this is reversible without loss.

The FKs are added as bare Integers. SQLite batch mode cannot emit an unnamed
FOREIGN KEY inside a table rebuild ("Constraint must have a name"), and FK
enforcement is off app-wide, so the ORM-side db.ForeignKey declaration is what
matters for joins.
"""
import sqlalchemy as sa
from alembic import op

revision = 'posig_0001'
down_revision = 'rrmulti_0001'
branch_labels = None
depends_on = None


NEW_COLUMNS = (
    ('prepared_by', sa.String(length=100)),
    ('checked_by', sa.String(length=100)),
    ('approved_by', sa.String(length=100)),
    ('submitted_by_id', sa.Integer()),
    ('submitted_at', sa.DateTime()),
)


def upgrade():
    existing = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('purchase_orders')}
    with op.batch_alter_table('purchase_orders') as batch:
        for name, type_ in NEW_COLUMNS:
            if name not in existing:
                batch.add_column(sa.Column(name, type_, nullable=True))


def downgrade():
    existing = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('purchase_orders')}
    with op.batch_alter_table('purchase_orders') as batch:
        for name, _ in reversed(NEW_COLUMNS):
            if name in existing:
                batch.drop_column(name)
