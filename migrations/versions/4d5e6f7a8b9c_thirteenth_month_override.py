"""Add thirteenth_month_override to payroll_run_lines (Task 13, R-06 Payroll
v1 P3 slice): a bool flag gating whether calculate_amounts() auto-aggregates
the 13th-month amount (service.compute_thirteenth_month, the standard
YTD-basic/12 formula) or preserves a manually-entered value already sitting
in the existing thirteenth_month column -- mirrors sales_invoices/
accounts_payable's vat_override/wt_override convention (a bool flag next to
the single amount column it gates).

DEPLOY NOTE: payroll_run_lines already exists (migration 2b3c4d5e6f7a). The
new column is NOT NULL with server_default='0' (False), so every existing
row backfills to "not overridden" -- correct for every line created before
this feature, none of which is a 13th-month line, since run_type='13th_month'
has been calc-inert (thirteenth_month always 0) until this task wired it up.

Revision ID: 4d5e6f7a8b9c
Revises: 3c4d5e6f7a8b
Create Date: 2026-07-14

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4d5e6f7a8b9c'
down_revision = '3c4d5e6f7a8b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('payroll_run_lines', schema=None) as batch_op:
        batch_op.add_column(sa.Column('thirteenth_month_override', sa.Boolean(),
                                       server_default='0', nullable=False))


def downgrade():
    with op.batch_alter_table('payroll_run_lines', schema=None) as batch_op:
        batch_op.drop_column('thirteenth_month_override')
