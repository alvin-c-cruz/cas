"""add bank_transfers table

Revision ID: 431260ceb58c
Revises: ec44eda6db34
Create Date: 2026-07-18 17:53:24.031542

R-04 slice 2: BankTransfer, RowVersioned (two-step inter-branch flow is
concurrency-sensitive). New table only -- inline FKs are safe (fresh create_table).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '431260ceb58c'
down_revision = 'ec44eda6db34'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('bank_transfers',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('transfer_number', sa.String(length=50), nullable=False),
        sa.Column('from_bank_account_id', sa.Integer(), sa.ForeignKey('bank_accounts.id'), nullable=False),
        sa.Column('to_bank_account_id', sa.Integer(), sa.ForeignKey('bank_accounts.id'), nullable=False),
        sa.Column('from_branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=False),
        sa.Column('to_branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=False),
        sa.Column('is_inter_branch', sa.Boolean(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('transfer_date', sa.Date(), nullable=False),
        sa.Column('memo', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('sender_je_id', sa.Integer(), sa.ForeignKey('journal_entries.id'), nullable=True),
        sa.Column('receiver_je_id', sa.Integer(), sa.ForeignKey('journal_entries.id'), nullable=True),
        sa.Column('reversal_je_id', sa.Integer(), sa.ForeignKey('journal_entries.id'), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('initiated_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('initiated_at', sa.DateTime(), nullable=True),
        sa.Column('confirmed_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('rejected_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('rejected_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('transfer_number', name='uq_bank_transfers_transfer_number'),
    )
    with op.batch_alter_table('bank_transfers', schema=None) as b:
        b.create_index('ix_bank_transfers_transfer_number', ['transfer_number'])
        b.create_index('ix_bank_transfers_from_branch_id', ['from_branch_id'])
        b.create_index('ix_bank_transfers_to_branch_id', ['to_branch_id'])
        b.create_index('ix_bank_transfers_status', ['status'])


def downgrade():
    with op.batch_alter_table('bank_transfers', schema=None) as b:
        b.drop_index('ix_bank_transfers_status')
        b.drop_index('ix_bank_transfers_to_branch_id')
        b.drop_index('ix_bank_transfers_from_branch_id')
        b.drop_index('ix_bank_transfers_transfer_number')
    op.drop_table('bank_transfers')
