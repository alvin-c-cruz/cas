"""Cheque payee per CDV, and a Check Payee Name on employees (plan item 2.3)

Owner, 28 Oct 2026: "the CDV should have option to change the Payee of the check in the CDV. the default
will come from the maintenance"; "employee should have option to change payee name. sometimes employee
has no own bank account." Owner, 2 Nov 2026: backfill existing CDVs from the alias they print today.

The backfill writes, on every CHEQUE CDV, exactly what its cheque prints today: the vendor's Check Payee
Name when set (and not blank), else the voucher's payee name (an employee's cheque prints the full name).
So resetting a vendor's alias later (V202 / V063 back to blank, owner's answer) cannot change an older
cheque's reprint. Non-cheque CDVs stay NULL. The downgrade drops both columns.

Revision ID: chqpay_0001
Revises: dslip_0001
Create Date: 2026-11-12
"""
import sqlalchemy as sa
from alembic import op

revision = 'chqpay_0001'
down_revision = 'dslip_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('cash_disbursement_vouchers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('check_payee_name', sa.String(length=200), nullable=True))
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.add_column(sa.Column('check_payee_name', sa.String(length=200), nullable=True))
    op.execute("""
        UPDATE cash_disbursement_vouchers
           SET check_payee_name = COALESCE(
                   (SELECT NULLIF(TRIM(v.check_payee_name), '')
                      FROM vendors v
                     WHERE v.id = cash_disbursement_vouchers.vendor_id
                       AND COALESCE(cash_disbursement_vouchers.payee_type, 'vendor') = 'vendor'),
                   vendor_name)
         WHERE payment_method = 'check'
    """)


def downgrade():
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.drop_column('check_payee_name')
    with op.batch_alter_table('cash_disbursement_vouchers', schema=None) as batch_op:
        batch_op.drop_column('check_payee_name')
