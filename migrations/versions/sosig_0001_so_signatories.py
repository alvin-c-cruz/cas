"""Per-document printed signatories for the Sales Order.

Owner directive 2026-08-21: the SO carries its own Prepared By / Noted By /
Approved By, typed on the form and printed on the document. The owner chose the
PurchaseOrder shape -- a new order carries the names forward from THAT user's own
last order -- over the company-wide setting PR and RR read, so there are no
settings keys to add here and nothing to back-fill.

Purely ADDITIVE and PURE SCHEMA: three nullable columns, nothing altered. A
pre-existing order keeps NULLs and prints the original "Name & Date" hand-sign
hint, exactly as it did before this shipped, so no historical printout changes.

Three `add_column`s inside `batch_alter_table` (this repo configures Migrate()
without render_as_batch, so plain ALTERs are not an option). Each column is a
bare String -- no FK, no default, no constraint -- so none of them hits the
"Constraint must have a name" batch trap.

Revision ID: sosig_0001
Revises: prsig_0001
"""
import sqlalchemy as sa
from alembic import op

revision = 'sosig_0001'
down_revision = 'prsig_0001'
branch_labels = None
depends_on = None

#: Roles match the Purchase Requisition's trio (owner directive), NOT the PO's,
#: whose middle slot is "Checked by".
_COLUMNS = ('prepared_by', 'noted_by', 'approved_by')


def upgrade():
    with op.batch_alter_table('sales_orders', schema=None) as batch_op:
        for name in _COLUMNS:
            batch_op.add_column(sa.Column(name, sa.String(length=100),
                                          nullable=True))


def downgrade():
    with op.batch_alter_table('sales_orders', schema=None) as batch_op:
        for name in reversed(_COLUMNS):
            batch_op.drop_column(name)
