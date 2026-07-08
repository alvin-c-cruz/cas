"""create employees table

Revision ID: 88f67c2cc4fb
Revises: c9e1f2a3b4d5
Create Date: 2026-07-08 08:29:09.671008

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '88f67c2cc4fb'
down_revision = 'c9e1f2a3b4d5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'employees',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('employee_no', sa.String(length=20), nullable=False),
        sa.Column('first_name', sa.String(length=100), nullable=False),
        sa.Column('middle_name', sa.String(length=100), nullable=True),
        sa.Column('last_name', sa.String(length=100), nullable=False),
        sa.Column('birthdate', sa.Date(), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('email', sa.String(length=120), nullable=True),
        sa.Column('tin', sa.String(length=50), nullable=True),
        sa.Column('sss_no', sa.String(length=50), nullable=True),
        sa.Column('philhealth_no', sa.String(length=50), nullable=True),
        sa.Column('pagibig_no', sa.String(length=50), nullable=True),
        sa.Column('date_hired', sa.Date(), nullable=True),
        sa.Column('employment_status', sa.String(length=30), nullable=True),
        sa.Column('position', sa.String(length=120), nullable=True),
        sa.Column('branch_id', sa.Integer(), nullable=False),
        sa.Column('tax_status_code', sa.String(length=10), nullable=True),
        sa.Column('qualified_dependents', sa.Integer(), nullable=True),
        sa.Column('is_minimum_wage', sa.Boolean(), nullable=True),
        sa.Column('pay_basis', sa.String(length=20), nullable=True),
        sa.Column('basic_rate', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('pay_frequency', sa.String(length=20), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.create_index('ix_employees_employee_no', ['employee_no'], unique=True)
        batch_op.create_index('ix_employees_branch_id', ['branch_id'], unique=False)
        batch_op.create_index('ix_employees_user_id', ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.drop_index('ix_employees_user_id')
        batch_op.drop_index('ix_employees_branch_id')
        batch_op.drop_index('ix_employees_employee_no')
    op.drop_table('employees')
