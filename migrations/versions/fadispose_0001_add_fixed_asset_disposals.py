"""add fixed asset disposals (R-05 Slice 3)

Revision ID: fadispose_0001
Revises: 041eda0bb5ad
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa

revision = 'fadispose_0001'
down_revision = '041eda0bb5ad'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'fixed_asset_disposals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('fixed_asset_id', sa.Integer(), nullable=False),
        sa.Column('disposal_date', sa.Date(), nullable=False),
        sa.Column('disposal_type', sa.String(length=10), nullable=False),
        sa.Column('proceeds_amount', sa.Numeric(15, 2), nullable=False, server_default='0'),
        sa.Column('proceeds_account_id', sa.Integer(), nullable=True),
        sa.Column('final_depreciation_amount', sa.Numeric(15, 2), nullable=False,
                  server_default='0'),
        sa.Column('cost_written_off', sa.Numeric(15, 2), nullable=False),
        sa.Column('accumulated_depreciation_written_off', sa.Numeric(15, 2), nullable=False),
        sa.Column('net_book_value_at_disposal', sa.Numeric(15, 2), nullable=False),
        sa.Column('gain_loss_amount', sa.Numeric(15, 2), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False, server_default='posted'),
        sa.Column('journal_entry_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['fixed_asset_id'], ['fixed_assets.id'],
                                name='fk_fixed_asset_disposals_asset'),
        sa.ForeignKeyConstraint(['proceeds_account_id'], ['accounts.id'],
                                name='fk_fixed_asset_disposals_proceeds_account'),
        sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entries.id'],
                                name='fk_fixed_asset_disposals_journal_entry'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'],
                                name='fk_fixed_asset_disposals_created_by'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'uq_fixed_asset_disposal_asset', 'fixed_asset_disposals', ['fixed_asset_id'],
        unique=True,
        sqlite_where=sa.text("status != 'void'"),
    )


def downgrade():
    op.drop_index('uq_fixed_asset_disposal_asset', table_name='fixed_asset_disposals')
    op.drop_table('fixed_asset_disposals')
