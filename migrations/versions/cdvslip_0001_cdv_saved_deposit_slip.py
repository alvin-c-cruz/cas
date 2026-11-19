"""A CDV keeps its own deposit-slip details (cash_disbursement_vouchers.slip_*)

CVS-1 A (owner, 14 Nov 2026; work order 2026-11-13-cv-level-cheque-payee-and-deposit-slip): "Save on this voucher" on
the deposit slip page keeps Account Name, Account Number, Bank/Branch and the slip form on the CDV, only where they
differ from the defaults. Four nullable columns; every existing voucher starts NULL (= use the defaults), so no slip
changes on upgrade.

Revision ID: cdvslip_0001
Revises: drnoso_0001
Create Date: 2026-11-17
"""
import sqlalchemy as sa
from alembic import op

revision = 'cdvslip_0001'
down_revision = 'drnoso_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('cash_disbursement_vouchers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('slip_account_name', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('slip_account_number', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('slip_check_bank', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('slip_form', sa.String(length=30), nullable=True))


def downgrade():
    with op.batch_alter_table('cash_disbursement_vouchers', schema=None) as batch_op:
        batch_op.drop_column('slip_form')
        batch_op.drop_column('slip_check_bank')
        batch_op.drop_column('slip_account_number')
        batch_op.drop_column('slip_account_name')
