"""add conversion_cost to production_runs

Revision ID: prodconv_0001
Revises: prodrun_0001
Create Date: 2026-08-02

R-07 Process Track slice P3. Conversion cost (labour + overhead) for the period is
entered MANUALLY on the run -- owner decision 2026-08-02, after the arc spec's
"reuse R-03a's ExpenseAllocationRule" turned out to be impossible (that driver is
product-line scoped, keyed on account_id and distributed across ProductCategory,
with no department and no period dimension; nothing in the app posted cost against
a department at all). See the dated correction in
docs/superpowers/specs/2026-07-19-manufacturing-r07-design.md.

Additive and nullable: existing rows keep NULL, which compute_run_costing() treats
as zero. Uses batch_alter_table -- SQLite cannot ALTER a table in place.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'prodconv_0001'
down_revision = 'prodrun_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('production_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('conversion_cost', sa.Numeric(precision=15, scale=2),
                                      nullable=True))


def downgrade():
    with op.batch_alter_table('production_runs', schema=None) as batch_op:
        batch_op.drop_column('conversion_cost')
