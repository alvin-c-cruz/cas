"""add depreciation runs + entries (R-05 Slice 2)

Revision ID: fadepr_0001
Revises: ffc3e66c04c0
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa

revision = 'fadepr_0001'
down_revision = 'ffc3e66c04c0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'depreciation_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('branch_id', sa.Integer(), nullable=False),
        sa.Column('period_year', sa.Integer(), nullable=False),
        sa.Column('period_month', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False, server_default='draft'),
        sa.Column('journal_entry_id', sa.Integer(), nullable=True),
        sa.Column('run_date', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id'],
                                name='fk_depreciation_runs_branch'),
        sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entries.id'],
                                name='fk_depreciation_runs_journal_entry'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'],
                                name='fk_depreciation_runs_created_by'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'uq_depreciation_run_period', 'depreciation_runs',
        ['branch_id', 'period_year', 'period_month'],
        unique=True,
        sqlite_where=sa.text("status != 'reversed'"),
    )

    op.create_table(
        'depreciation_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('fixed_asset_id', sa.Integer(), nullable=False),
        sa.Column('depreciation_amount', sa.Numeric(15, 2), nullable=False),
        sa.Column('accumulated_depreciation_after', sa.Numeric(15, 2), nullable=False),
        sa.Column('net_book_value_after', sa.Numeric(15, 2), nullable=False),
        sa.Column('units_used', sa.Numeric(15, 2), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['depreciation_runs.id'],
                                name='fk_depreciation_entries_run'),
        sa.ForeignKeyConstraint(['fixed_asset_id'], ['fixed_assets.id'],
                                name='fk_depreciation_entries_fixed_asset'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_depreciation_entries_run_id', 'depreciation_entries', ['run_id'])
    op.create_index('ix_depreciation_entries_fixed_asset_id', 'depreciation_entries',
                    ['fixed_asset_id'])


def downgrade():
    op.drop_index('ix_depreciation_entries_fixed_asset_id', table_name='depreciation_entries')
    op.drop_index('ix_depreciation_entries_run_id', table_name='depreciation_entries')
    op.drop_table('depreciation_entries')
    op.drop_index('uq_depreciation_run_period', table_name='depreciation_runs')
    op.drop_table('depreciation_runs')
