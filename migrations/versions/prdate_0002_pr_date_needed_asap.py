"""Purchase Requisition: add date_needed_asap

Revision ID: prdate_0002
Revises: prdate_0001
Create Date: 2026-08-14

ASAP as an alternative to a specific Date Needed -- the goods are wanted
immediately, so no date is invented.

NOT NULL with server_default '0': the column has to be non-null for the template
branches to be safe, and existing rows need a value. The server_default is what
supplies it during the table rebuild -- without it the ALTER fails on any table
that already has rows, which is every real database here.

Mutual exclusivity (ASAP clears date_needed) is enforced in the view layer, not
by a CHECK constraint: SQLite cannot add one without a full table rebuild, and
batch mode would then have to reproduce it on every future column change.
"""
import sqlalchemy as sa
from alembic import op

revision = 'prdate_0002'
down_revision = 'prdate_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('purchase_requests', schema=None) as batch_op:
        batch_op.add_column(sa.Column('date_needed_asap', sa.Boolean(),
                                      nullable=False, server_default='0'))


def downgrade():
    with op.batch_alter_table('purchase_requests', schema=None) as batch_op:
        batch_op.drop_column('date_needed_asap')
