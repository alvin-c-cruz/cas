"""Vendor bank details (bank, account name, account number)

Owner, 2026-09-23: some vendors are paid by bank deposit, so the vendor master
carries the account they are paid into, and a Bank Transfer / Online CDV shows it.
ONE account per vendor (owner's choice), hence plain columns and no child table.

All three are nullable text. The account number is a String, never an Integer:
leading zeros and dashes are part of it.

Revision ID: vbank_0001
Revises: mrgheads_0001
Create Date: 2026-09-23
"""
import sqlalchemy as sa
from alembic import op

revision = 'vbank_0001'
down_revision = 'mrgheads_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('vendors', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bank_name', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('bank_account_name', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('bank_account_number', sa.String(length=50), nullable=True))


def downgrade():
    with op.batch_alter_table('vendors', schema=None) as batch_op:
        batch_op.drop_column('bank_account_number')
        batch_op.drop_column('bank_account_name')
        batch_op.drop_column('bank_name')
