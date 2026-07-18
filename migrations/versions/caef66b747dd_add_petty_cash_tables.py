"""add petty_cash tables

Revision ID: caef66b747dd
Revises: ffc3e66c04c0
Create Date: 2026-07-18 21:26:43.233327

R-04 slice 4: PettyCashFund + PettyCashVoucher (posts NO JE) +
PettyCashReplenishment (RowVersioned, the JE-posting event).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'caef66b747dd'
down_revision = 'ffc3e66c04c0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('petty_cash_funds',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('custodian', sa.String(length=200), nullable=True),
        sa.Column('float_amount', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('funding_bank_account_id', sa.Integer(), sa.ForeignKey('bank_accounts.id'), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('account_id', name='uq_petty_cash_funds_account_id'),
    )
    with op.batch_alter_table('petty_cash_funds', schema=None) as b:
        b.create_index('ix_petty_cash_funds_branch_id', ['branch_id'])
        b.create_index('ix_petty_cash_funds_code', ['code'])

    op.create_table('petty_cash_replenishments',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('fund_id', sa.Integer(), sa.ForeignKey('petty_cash_funds.id'), nullable=False),
        sa.Column('replenishment_number', sa.String(length=50), nullable=False),
        sa.Column('replenishment_date', sa.Date(), nullable=False),
        sa.Column('physical_cash_counted', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('vouchers_total', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('short_over_amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'),
        sa.Column('replenish_amount', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('journal_entry_id', sa.Integer(), sa.ForeignKey('journal_entries.id'), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('posted_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('posted_at', sa.DateTime(), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('replenishment_number', name='uq_petty_cash_replenishments_number'),
    )
    with op.batch_alter_table('petty_cash_replenishments', schema=None) as b:
        b.create_index('ix_petty_cash_replenishments_fund_id', ['fund_id'])

    op.create_table('petty_cash_vouchers',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('fund_id', sa.Integer(), sa.ForeignKey('petty_cash_funds.id'), nullable=False),
        sa.Column('voucher_number', sa.String(length=50), nullable=False),
        sa.Column('voucher_date', sa.Date(), nullable=False),
        sa.Column('payee', sa.String(length=200), nullable=False),
        sa.Column('expense_account_id', sa.Integer(), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('receipt_ref', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='held'),
        sa.Column('replenishment_id', sa.Integer(), sa.ForeignKey('petty_cash_replenishments.id'), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('voucher_number', name='uq_petty_cash_vouchers_number'),
    )
    with op.batch_alter_table('petty_cash_vouchers', schema=None) as b:
        b.create_index('ix_petty_cash_vouchers_fund_id', ['fund_id'])
        b.create_index('ix_petty_cash_vouchers_status', ['status'])


def downgrade():
    op.drop_table('petty_cash_vouchers')
    op.drop_table('petty_cash_replenishments')
    op.drop_table('petty_cash_funds')
