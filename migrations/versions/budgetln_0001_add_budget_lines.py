"""add budget_lines table

Revision ID: budgetln_0001
Revises: 600ef1b526b4
Create Date: 2026-07-19 00:00:00.000000

R-09 Slice 1: BudgetLine -- flat matrix of (branch, account, fiscal_year, month) ->
amount. No header table; see
docs/superpowers/specs/2026-07-19-budgeting-entry-r09-slice1-design.md.
"""
from alembic import op
import sqlalchemy as sa


revision = 'budgetln_0001'
down_revision = '600ef1b526b4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('budget_lines',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=False),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('fiscal_year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'),
        sa.Column('updated_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('branch_id', 'account_id', 'fiscal_year', 'month',
                             name='uq_budget_line_branch_account_year_month'),
    )
    with op.batch_alter_table('budget_lines', schema=None) as b:
        b.create_index('ix_budget_lines_branch_id', ['branch_id'])
        b.create_index('ix_budget_lines_account_id', ['account_id'])
        b.create_index('ix_budget_lines_fiscal_year', ['fiscal_year'])


def downgrade():
    op.drop_table('budget_lines')
