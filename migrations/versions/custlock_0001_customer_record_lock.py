"""Customer record lock: is_locked + who/when provenance.

Staff may maintain customer data (owner directive 2026-08-30); an approver may
freeze a settled record against them. See app/customers/models.py for the rule.

Additive and non-destructive: every existing customer reads UNLOCKED, so nothing
that was editable yesterday becomes uneditable when this lands. There is no
backfill for that reason -- an unlocked record has no locker and no lock time, and
writing a fabricated one would be a false fact about who froze it.

`locked_by_id` is a BARE Integer here, not sa.ForeignKey: SQLite batch mode cannot
emit an unnamed FK inside its table rebuild ("Constraint must have a name"), and
the app runs with FK enforcement off anyway. The ORM side still declares
db.ForeignKey('users.id') so joins and `locked_by` work -- same split as
SalesOrder.quotation_id (29500ade76f8).

Revision ID: custlock_0001
Revises: sochk_0001
"""
import sqlalchemy as sa
from alembic import op

revision = 'custlock_0001'
down_revision = 'sochk_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('customers', schema=None) as batch_op:
        # server_default='0' is required, not cosmetic: the column is NOT NULL and
        # the table already has rows, so without it SQLite cannot fill the
        # existing ones and the rebuild fails.
        batch_op.add_column(sa.Column('is_locked', sa.Boolean(), nullable=False,
                                      server_default='0'))
        batch_op.add_column(sa.Column('locked_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('locked_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.drop_column('locked_at')
        batch_op.drop_column('locked_by_id')
        batch_op.drop_column('is_locked')
