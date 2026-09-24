"""CDV polymorphic payee: vendor OR employee

The Cash Disbursement Voucher takes the AP Voucher's payee shape
(d9bebfed48f3, 2026-07-08): payee_type + payee_id, vendor_id nullable.
Owner, 2026-09-24: employee names were unreachable from a CV -- the CV had
no employee payee at all, so employee APVs could not be paid.

Backfill: every existing CDV is a vendor payment.

Downgrade REFUSES when any employee CDV exists: vendor_id NOT NULL cannot be
restored over rows that legitimately have none. The pre-deploy backup is the
rollback in that case.

Revision ID: cdvpay_0001
Revises: vbank_0001
Create Date: 2026-09-24
"""
import sqlalchemy as sa
from alembic import op

revision = 'cdvpay_0001'
down_revision = 'vbank_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('cash_disbursement_vouchers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payee_type', sa.String(length=20), nullable=False,
                                      server_default='vendor'))
        batch_op.add_column(sa.Column('payee_id', sa.Integer(), nullable=False, server_default='0'))
        batch_op.alter_column('vendor_id', existing_type=sa.Integer(), nullable=True)
        batch_op.create_index('ix_cash_disbursement_vouchers_payee_type', ['payee_type'], unique=False)
    op.execute("UPDATE cash_disbursement_vouchers SET payee_type='vendor', payee_id=vendor_id "
               "WHERE payee_id=0 OR payee_id IS NULL")


def downgrade():
    conn = op.get_bind()
    employees = conn.execute(sa.text(
        "SELECT COUNT(*) FROM cash_disbursement_vouchers WHERE payee_type='employee'")).scalar()
    if employees:
        raise RuntimeError(f'{employees} employee-payee CDV(s) exist; vendor_id NOT NULL cannot be '
                           f'restored over them. Restore the pre-deploy backup instead.')
    with op.batch_alter_table('cash_disbursement_vouchers', schema=None) as batch_op:
        batch_op.drop_index('ix_cash_disbursement_vouchers_payee_type')
        batch_op.alter_column('vendor_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column('payee_id')
        batch_op.drop_column('payee_type')
