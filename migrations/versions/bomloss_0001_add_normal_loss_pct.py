"""add normal_loss_pct to bills_of_material

Revision ID: bomloss_0001
Revises: prodclose_0001
Create Date: 2026-08-03

R-07 Process Track slice P6. The percentage of units started that a process is
expected to lose; loss beyond it is abnormal and gets costed out rather than
absorbed into the price of good units.

NULLABLE WITH NO DEFAULT, deliberately. NULL means "no expectation set", which must
behave exactly as the app does today: no allowance, therefore no abnormal loss,
therefore all loss absorbed. A server_default of 0 would mean "expected to lose
nothing" and would silently reclassify every existing run's ordinary shrinkage as an
abnormal loss the moment this migration ran.

Uses batch_alter_table -- SQLite cannot ALTER in place. Verified on a real migrated
DB (up and down) with the bills_of_material row count and index set checked either
side of the rebuild.
"""
from alembic import op
import sqlalchemy as sa


revision = 'bomloss_0001'
down_revision = 'prodclose_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('bills_of_material', schema=None) as batch_op:
        batch_op.add_column(sa.Column('normal_loss_pct', sa.Numeric(precision=5, scale=2),
                                      nullable=True))


def downgrade():
    with op.batch_alter_table('bills_of_material', schema=None) as batch_op:
        batch_op.drop_column('normal_loss_pct')
