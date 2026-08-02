"""add period-close + WIP carry-forward columns to production_runs

Revision ID: prodclose_0001
Revises: prodconv_0001
Create Date: 2026-08-03

R-07 Process Track slice P4. Six additive columns, owner-approved 2026-08-02.

The two beginning_wip_* columns are NOT NULL with a server_default of 0 -- every
run has a beginning WIP even when it is zero, and a NULL there would silently drop
out of the cost pool's sum instead of adding nothing. The server_default is what
lets them be NOT NULL on a table that already holds rows.

The four close columns are nullable: an open run has not been closed.

closed_by_id is a PLAIN Integer, not sa.ForeignKey. A batch add_column cannot emit
an unnamed FK inside SQLite's table rebuild ("Constraint must have a name"), and
SQLite FK enforcement is off app-wide, so nothing is lost. Same choice as
SalesOrder.quotation_id (29500ade76f8).

VERIFICATION NOTE: batch_alter_table rebuilds the table, and it reflects the
EXISTING schema to do so -- a conftest create_all() test builds today's model and
therefore cannot prove this migration preserved anything. This one was run against
a real migrated database and all four production_runs indexes
(ix_production_runs_run_number / _department_id / _branch_id / _status) were
confirmed present afterwards, along with the pre-existing row count. See memory
migration-verify-on-real-db-copy.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'prodclose_0001'
down_revision = 'prodconv_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('production_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('beginning_wip_units', sa.Numeric(precision=15, scale=4),
                                      nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('beginning_wip_cost', sa.Numeric(precision=15, scale=2),
                                      nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('ending_wip_cost', sa.Numeric(precision=15, scale=2),
                                      nullable=True))
        batch_op.add_column(sa.Column('transferred_unit_cost', sa.Numeric(precision=15, scale=2),
                                      nullable=True))
        batch_op.add_column(sa.Column('closed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('closed_by_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('production_runs', schema=None) as batch_op:
        batch_op.drop_column('closed_by_id')
        batch_op.drop_column('closed_at')
        batch_op.drop_column('transferred_unit_cost')
        batch_op.drop_column('ending_wip_cost')
        batch_op.drop_column('beginning_wip_cost')
        batch_op.drop_column('beginning_wip_units')
