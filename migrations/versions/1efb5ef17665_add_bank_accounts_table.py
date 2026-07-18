"""add bank_accounts table

Revision ID: 1efb5ef17665
Revises: c4f8e1a9d5b7
Create Date: 2026-07-18 10:33:21.382959

R-04 slice 1: a branch-scoped 1:1 label over a COA cash/bank GL account. No changes
to any existing table -- CRV/CDV keep storing cash_account_id exactly as today.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1efb5ef17665'
down_revision = 'c4f8e1a9d5b7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('bank_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('bank_name', sa.String(length=200), nullable=True),
        sa.Column('account_number', sa.String(length=50), nullable=True),
        sa.Column('account_type', sa.String(length=30), nullable=True),
        sa.Column('opening_balance', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'),
        sa.Column('opening_date', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_by', sa.String(length=80), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('account_id', name='uq_bank_accounts_account_id'),
    )
    with op.batch_alter_table('bank_accounts', schema=None) as b:
        b.create_index('ix_bank_accounts_branch_id', ['branch_id'])
        b.create_index('ix_bank_accounts_code', ['code'])


def downgrade():
    with op.batch_alter_table('bank_accounts', schema=None) as b:
        b.drop_index('ix_bank_accounts_code')
        b.drop_index('ix_bank_accounts_branch_id')
    op.drop_table('bank_accounts')
