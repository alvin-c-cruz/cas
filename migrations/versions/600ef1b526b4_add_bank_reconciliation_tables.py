"""add bank_reconciliation tables

Revision ID: 600ef1b526b4
Revises: fadispose_0001
Create Date: 2026-07-19 00:05:24.347745

R-04 slice 3: BankReconciliation (RowVersioned, snapshot totals) + ReconciliationItem
(clearing table, je_line_id globally unique -- a line clears in at most one rec ever).
core journal_entry_lines table is UNTOUCHED.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '600ef1b526b4'
down_revision = 'fadispose_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('bank_reconciliations',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('bank_account_id', sa.Integer(), sa.ForeignKey('bank_accounts.id'), nullable=False),
        sa.Column('statement_date', sa.Date(), nullable=False),
        sa.Column('statement_ending_balance', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('beginning_balance', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('book_balance', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('cleared_debits', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('cleared_credits', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('outstanding_deposits', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('outstanding_checks', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('adjusted_balance', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('reconciled_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('reconciled_at', sa.DateTime(), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table('bank_reconciliations', schema=None) as b:
        b.create_index('ix_bank_reconciliations_bank_account_id', ['bank_account_id'])

    op.create_table('reconciliation_items',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('reconciliation_id', sa.Integer(), sa.ForeignKey('bank_reconciliations.id'), nullable=False),
        sa.Column('je_line_id', sa.Integer(), sa.ForeignKey('journal_entry_lines.id'), nullable=False),
        sa.Column('cleared_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('je_line_id', name='uq_reconciliation_items_je_line_id'),
    )
    with op.batch_alter_table('reconciliation_items', schema=None) as b:
        b.create_index('ix_reconciliation_items_reconciliation_id', ['reconciliation_id'])
        b.create_index('ix_reconciliation_items_je_line_id', ['je_line_id'])


def downgrade():
    op.drop_table('reconciliation_items')
    op.drop_table('bank_reconciliations')
