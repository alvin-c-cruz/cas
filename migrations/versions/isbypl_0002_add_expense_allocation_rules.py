"""add expense_allocation_rules table (Phase 3b: Income Statement by Product Line)

Revision ID: isbypl_0002
Revises: isbypl_0001
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa

revision = 'isbypl_0002'
down_revision = 'isbypl_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'expense_allocation_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('basis', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'],
                                name='fk_expense_allocation_rules_account'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'],
                                name='fk_expense_allocation_rules_created_by'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('uq_expense_allocation_rules_account', 'expense_allocation_rules',
                    ['account_id'], unique=True)


def downgrade():
    op.drop_index('uq_expense_allocation_rules_account', table_name='expense_allocation_rules')
    op.drop_table('expense_allocation_rules')
