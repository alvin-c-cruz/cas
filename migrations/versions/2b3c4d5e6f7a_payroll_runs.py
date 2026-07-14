"""PayrollRun + PayrollRunLine tables, with a partial unique index enforcing
at most one non-voided/cancelled run per (branch, run_type, pay_frequency,
period_year, period_month, semi_period).

semi_period is NOT NULL (default 0 = "not applicable" for every pay_frequency
other than semi_monthly, which uses 1/2 for the two cutoffs). This is
deliberate: SQLite -- like every SQL engine -- treats NULL as distinct from
NULL inside a UNIQUE index, so if semi_period were nullable, two monthly runs
for the SAME period would both carry semi_period=NULL and the partial unique
index would silently fail to reject the duplicate (proven while writing the
model's tests: a nullable semi_period let a duplicate insert through with no
IntegrityError). Using 0 as a real, comparable sentinel value closes that gap.

DEPLOY NOTE: this is a brand-new table pair, so there is no pre-existing-data
migration risk (unlike the CDV check-serial index, which had to consider
already-duplicate rows).

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f
Create Date: 2026-07-13

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2b3c4d5e6f7a'
down_revision = '1a2b3c4d5e6f'
branch_labels = None
depends_on = None

_INDEX = 'uq_payroll_run_period'
_TABLE = 'payroll_runs'
_WHERE = "status NOT IN ('voided', 'cancelled')"


def upgrade():
    op.create_table('payroll_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('row_version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('run_number', sa.String(length=50), nullable=False),
    sa.Column('branch_id', sa.Integer(), nullable=False),
    sa.Column('run_type', sa.String(length=20), nullable=False),
    sa.Column('pay_frequency', sa.String(length=20), nullable=False),
    sa.Column('period_year', sa.Integer(), nullable=False),
    sa.Column('period_month', sa.Integer(), nullable=False),
    sa.Column('semi_period', sa.Integer(), server_default='0', nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('pay_date', sa.Date(), nullable=False),
    sa.Column('semi_timing', sa.String(length=20), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('journal_entry_id', sa.Integer(), nullable=True),
    sa.Column('total_gross', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('total_taxable', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('total_nontax', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('total_sss_ee', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('total_sss_er', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('total_sss_ec', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('total_philhealth_ee', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('total_philhealth_er', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('total_pagibig_ee', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('total_pagibig_er', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('total_wht', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('total_sss_loan', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('total_pagibig_loan', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('total_thirteenth_month', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('total_net_pay', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('posted_by_id', sa.Integer(), nullable=True),
    sa.Column('voided_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('posted_at', sa.DateTime(), nullable=True),
    sa.Column('voided_at', sa.DateTime(), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(), nullable=True),
    sa.Column('void_reason', sa.String(length=255), nullable=True),
    sa.Column('cancel_reason', sa.String(length=500), nullable=True),
    sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], ),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entries.id'], ),
    sa.ForeignKeyConstraint(['posted_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['voided_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('payroll_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_payroll_runs_branch_id'), ['branch_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_payroll_runs_run_number'), ['run_number'], unique=True)
        batch_op.create_index(batch_op.f('ix_payroll_runs_status'), ['status'], unique=False)

    op.create_index(_INDEX, _TABLE,
                    ['branch_id', 'run_type', 'pay_frequency', 'period_year',
                     'period_month', 'semi_period'],
                    unique=True, sqlite_where=sa.text(_WHERE))

    op.create_table('payroll_run_lines',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('line_number', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.Integer(), nullable=False),
    sa.Column('employee_name', sa.String(length=200), nullable=False),
    sa.Column('pay_basis', sa.String(length=20), nullable=False),
    sa.Column('rate', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('tax_status_code', sa.String(length=10), nullable=True),
    sa.Column('is_mwe', sa.Boolean(), nullable=False),
    sa.Column('days', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('hours', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('ot_pay', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('holiday_pay', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('taxable_allowance', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('nontax_allowance', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('basic_gross', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('gross_pay', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('sss_msc', sa.Numeric(precision=15, scale=2), nullable=True),
    sa.Column('sss_ee', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('sss_er', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('sss_ec', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('philhealth_ee', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('philhealth_er', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('pagibig_ee', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('pagibig_er', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('taxable_comp', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('wht', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('wht_bracket_id', sa.Integer(), nullable=True),
    sa.Column('sss_loan', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('pagibig_loan', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('thirteenth_month', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('net_pay', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['payroll_runs.id'], ),
    sa.ForeignKeyConstraint(['wht_bracket_id'], ['compensation_wht_brackets.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('payroll_run_lines', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_payroll_run_lines_employee_id'), ['employee_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_payroll_run_lines_run_id'), ['run_id'], unique=False)


def downgrade():
    with op.batch_alter_table('payroll_run_lines', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_payroll_run_lines_run_id'))
        batch_op.drop_index(batch_op.f('ix_payroll_run_lines_employee_id'))

    op.drop_table('payroll_run_lines')

    op.drop_index(_INDEX, table_name=_TABLE)
    with op.batch_alter_table('payroll_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_payroll_runs_status'))
        batch_op.drop_index(batch_op.f('ix_payroll_runs_run_number'))
        batch_op.drop_index(batch_op.f('ix_payroll_runs_branch_id'))

    op.drop_table('payroll_runs')
