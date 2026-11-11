"""Payee bank details for the deposit slip: employees' bank account, and the slip form on both

Owner, 10 Nov 2026, on the slip page's form dropdown: "I think its better to have the same
dropdown in vendor maintenance"; design approved "VS-1 A, VS-2 A, VS-3 A, VS-4 A, VS-5 A".
Employees get the vendor's three bank columns (vbank_0001), so a payroll CDV's slip fills
itself ("EMP-B, yes queue it"), and both tables get deposit_slip_form, a key of
app.common.deposit_slip.FORMS (VS-4 A); one migration for both (VS-5 A). Every column is
nullable and starts NULL: no existing vendor or employee changes (VS-1 A). The account
number is text, never an integer: leading zeros matter.

Revision ID: dslip_0001
Revises: invunit_0001
Create Date: 2026-11-10
"""
import sqlalchemy as sa
from alembic import op

revision = 'dslip_0001'
down_revision = 'invunit_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('vendors', schema=None) as batch_op:
        batch_op.add_column(sa.Column('deposit_slip_form', sa.String(length=30), nullable=True))
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bank_name', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('bank_account_name', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('bank_account_number', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('deposit_slip_form', sa.String(length=30), nullable=True))


def downgrade():
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.drop_column('deposit_slip_form')
        batch_op.drop_column('bank_account_number')
        batch_op.drop_column('bank_account_name')
        batch_op.drop_column('bank_name')
    with op.batch_alter_table('vendors', schema=None) as batch_op:
        batch_op.drop_column('deposit_slip_form')
