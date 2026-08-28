"""The Sales Order gains a fourth printed signatory: Checked by.

Owner request 2026-08-28. PhilGen's Sales Order pad carries Prepared / Checked /
Noted / Approved; `checked_by` was the one slot the document did not have. It
sits SECOND, the order the blocks are signed in and printed in.

Applied APP-WIDE by owner decision (option A). CAS is one codebase across every
instance, so an instance that does not use the slot simply leaves it NULL -- and
a NULL prints the same "Name & Date" ruled line the other three already print
when blank, which is a line to sign by hand, not missing data.

Purely ADDITIVE and PURE SCHEMA: one nullable column, nothing altered, nothing
back-filled. Checked against every client backup before writing: four of the
five predate sosig_0001 entirely (no `approved_by` column yet) and PhilGen has
zero sales orders, so there is no signatory data anywhere in the fleet for this
to disturb.

One `add_column` inside `batch_alter_table` -- this repo configures Migrate()
without render_as_batch, so a plain ALTER is not an option. The column is a bare
String: no FK, no default, no constraint, so it cannot hit the "Constraint must
have a name" batch trap.

Revision ID: sochk_0001
Revises: sosig_0001
"""
import sqlalchemy as sa
from alembic import op

revision = 'sochk_0001'
down_revision = 'sosig_0001'
branch_labels = None
depends_on = None

_COLUMN = 'checked_by'


def upgrade():
    with op.batch_alter_table('sales_orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column(_COLUMN, sa.String(length=100),
                                      nullable=True))


def downgrade():
    with op.batch_alter_table('sales_orders', schema=None) as batch_op:
        batch_op.drop_column(_COLUMN)
