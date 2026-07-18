"""narrow products.standard_cost from Numeric(15,4) to Numeric(15,2)

R-03/R-03a collision resolution (Option A, see
docs/superpowers/plans/2026-07-19-product-standard-cost-collision-decision.md):
R-03a slice 2 (isbypl_0001) added standard_cost as Numeric(15,4), an unexamined
default. R-03 slice 1 reuses the same column and narrows it to Numeric(15,2) to
match every other monetary field on Product (default_unit_price, etc.) and the
rest of the codebase's convention. No data exists in this column yet (confirmed
directly against the real instance/cas.db before writing this migration), so
there is no precision-loss risk.

Revision ID: stdcost_0001
Revises: budgetln_0001
Create Date: 2026-07-19

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'stdcost_0001'
down_revision = 'budgetln_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.alter_column('standard_cost',
                              existing_type=sa.Numeric(precision=15, scale=4),
                              type_=sa.Numeric(precision=15, scale=2))


def downgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.alter_column('standard_cost',
                              existing_type=sa.Numeric(precision=15, scale=2),
                              type_=sa.Numeric(precision=15, scale=4))
