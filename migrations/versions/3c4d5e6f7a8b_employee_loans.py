"""EmployeeLoan table (SSS/Pag-IBIG salary-loan amortization schedules) plus
sss_loan_id/pagibig_loan_id columns on payroll_run_lines recording WHICH
specific loan record a posted line's deduction was drawn from -- needed for
an exact reversal on cancel (a loan's monthly_amortization could change
between post and cancel; the line's own already-computed sss_loan/
pagibig_loan amount, keyed to this FK, is what gets applied/restored, never
a fresh recompute -- see app/payroll/service.py's apply_loan_balances/
restore_loan_balances docstrings).

status is one of 'active' / 'paid' / 'cancelled'. A partial unique index
enforces AT MOST ONE 'active' loan per (employee_id, loan_type) --
PayrollRunLine.calculate_amounts() looks up "the" active loan for a type
with a plain filter_by(...).first(), and this index makes that lookup
well-defined rather than silently picking an arbitrary row among several.

sss_loan_id/pagibig_loan_id are added as PLAIN Integer columns (no inline
sa.ForeignKey) per CLAUDE.md's "Batch add_column cannot carry an inline
sa.ForeignKey" gotcha -- SQLite batch mode raises "Constraint must have a
name" for an unnamed FK inside a table rebuild. The ORM side still declares
db.ForeignKey for normal relationship joins; only the migration column is bare.

DEPLOY NOTE: employee_loans is a brand-new table (no pre-existing-data
migration risk). payroll_run_lines already exists (migration 2b3c4d5e6f7a)
-- the two new columns are nullable, so existing rows backfill to NULL
(meaning "no loan referenced"), which is exactly correct for every line that
predates this feature.

Revision ID: 3c4d5e6f7a8b
Revises: 2b3c4d5e6f7a
Create Date: 2026-07-14

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3c4d5e6f7a8b'
down_revision = '2b3c4d5e6f7a'
branch_labels = None
depends_on = None

_INDEX = 'uq_employee_loan_active_per_type'
_TABLE = 'employee_loans'
_WHERE = "status = 'active'"


def upgrade():
    op.create_table('employee_loans',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.Integer(), nullable=False),
    sa.Column('loan_type', sa.String(length=20), nullable=False),
    sa.Column('principal', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('monthly_amortization', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('balance', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('employee_loans', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_employee_loans_employee_id'), ['employee_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_employee_loans_status'), ['status'], unique=False)

    op.create_index(_INDEX, _TABLE, ['employee_id', 'loan_type'],
                     unique=True, sqlite_where=sa.text(_WHERE))

    with op.batch_alter_table('payroll_run_lines', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sss_loan_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('pagibig_loan_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('payroll_run_lines', schema=None) as batch_op:
        batch_op.drop_column('pagibig_loan_id')
        batch_op.drop_column('sss_loan_id')

    op.drop_index(_INDEX, table_name=_TABLE)
    with op.batch_alter_table('employee_loans', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_employee_loans_status'))
        batch_op.drop_index(batch_op.f('ix_employee_loans_employee_id'))

    op.drop_table('employee_loans')
