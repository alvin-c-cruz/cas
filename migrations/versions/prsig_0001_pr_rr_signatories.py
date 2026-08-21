"""Per-document printed signatories for Purchase Requisitions and Receiving Reports.

Owner directive 2026-08-21: match PurchaseOrder, which stores its three signatory
names ON the document. PR and RR printed from a single company-wide setting, so a
one-off signatory became permanent for every future printout.

Purely ADDITIVE and PURE SCHEMA -- six nullable columns, nothing altered, nothing
backfilled. The owner confirmed no official requisition has been recorded yet, so
there is no historical row whose printout would change; a new document pre-fills
from the existing company setting in the VIEW, which is where that belongs.

Six `add_column`s inside `batch_alter_table` (this repo configures Migrate()
without render_as_batch, so plain ALTERs are not an option). Each column is a
bare String -- no FK, no default, no constraint -- so none of them hits the
"Constraint must have a name" batch trap.

Revision ID: prsig_0001
Revises: pramd_0001
"""
import sqlalchemy as sa
from alembic import op

revision = 'prsig_0001'
down_revision = 'pramd_0001'
branch_labels = None
depends_on = None

#: (table, columns) -- role labels differ per document ON PURPOSE and match what
#: each one already prints: a receipt is checked and received, not approved.
_ADDITIONS = (
    ('purchase_requests', ('prepared_by', 'noted_by', 'approved_by')),
    ('receiving_reports', ('prepared_by', 'checked_by', 'received_by')),
)


def upgrade():
    for table, columns in _ADDITIONS:
        with op.batch_alter_table(table, schema=None) as batch_op:
            for name in columns:
                batch_op.add_column(sa.Column(name, sa.String(length=100),
                                              nullable=True))


def downgrade():
    for table, columns in reversed(_ADDITIONS):
        with op.batch_alter_table(table, schema=None) as batch_op:
            for name in reversed(columns):
                batch_op.drop_column(name)
