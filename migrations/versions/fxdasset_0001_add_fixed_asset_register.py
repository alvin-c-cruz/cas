"""add fixed asset register (asset_categories + fixed_assets)

Revision ID: fxdasset_0001
Revises: 8242857b00da
Create Date: 2026-07-18
"""
from alembic import op
import sqlalchemy as sa

revision = 'fxdasset_0001'
down_revision = '8242857b00da'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'asset_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('default_useful_life_months', sa.Integer(), nullable=True),
        sa.Column('default_depreciation_method', sa.String(length=20), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'],
                                name='fk_asset_categories_created_by'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_asset_categories_name', 'asset_categories', ['name'], unique=True)

    op.create_table(
        'fixed_assets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('branch_id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('acquisition_source_type', sa.String(length=10), nullable=False),
        sa.Column('acquisition_source_id', sa.Integer(), nullable=True),
        sa.Column('acquisition_source_line_id', sa.Integer(), nullable=True),
        sa.Column('acquisition_date', sa.Date(), nullable=False),
        sa.Column('acquisition_cost', sa.Numeric(15, 2), nullable=False),
        sa.Column('cost_account_id', sa.Integer(), nullable=False),
        sa.Column('accumulated_depreciation_account_id', sa.Integer(), nullable=False),
        sa.Column('depreciation_expense_account_id', sa.Integer(), nullable=False),
        sa.Column('depreciation_method', sa.String(length=20), nullable=False),
        sa.Column('useful_life_months', sa.Integer(), nullable=True),
        sa.Column('declining_balance_rate', sa.Numeric(5, 2), nullable=True),
        sa.Column('total_estimated_units', sa.Numeric(15, 2), nullable=True),
        sa.Column('salvage_value', sa.Numeric(15, 2), nullable=False, server_default='0'),
        sa.Column('opening_accumulated_depreciation', sa.Numeric(15, 2), nullable=False,
                  server_default='0'),
        sa.Column('status', sa.String(length=10), nullable=False, server_default='active'),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], name='fk_fixed_assets_branch'),
        sa.ForeignKeyConstraint(['category_id'], ['asset_categories.id'],
                                name='fk_fixed_assets_category'),
        sa.ForeignKeyConstraint(['cost_account_id'], ['accounts.id'],
                                name='fk_fixed_assets_cost_account'),
        sa.ForeignKeyConstraint(['accumulated_depreciation_account_id'], ['accounts.id'],
                                name='fk_fixed_assets_accum_dep_account'),
        sa.ForeignKeyConstraint(['depreciation_expense_account_id'], ['accounts.id'],
                                name='fk_fixed_assets_dep_expense_account'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'],
                                name='fk_fixed_assets_created_by'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_fixed_assets_code', 'fixed_assets', ['code'], unique=True)
    op.create_index('ix_fixed_assets_branch_id', 'fixed_assets', ['branch_id'])
    op.create_index('ix_fixed_assets_status', 'fixed_assets', ['status'])
    op.create_index(
        'uq_fixed_assets_acquisition_source', 'fixed_assets',
        ['acquisition_source_type', 'acquisition_source_id', 'acquisition_source_line_id'],
        unique=True,
        sqlite_where=sa.text("acquisition_source_type != 'opening'"),
    )


def downgrade():
    op.drop_index('uq_fixed_assets_acquisition_source', table_name='fixed_assets')
    op.drop_index('ix_fixed_assets_status', table_name='fixed_assets')
    op.drop_index('ix_fixed_assets_branch_id', table_name='fixed_assets')
    op.drop_index('ix_fixed_assets_code', table_name='fixed_assets')
    op.drop_table('fixed_assets')
    op.drop_index('ix_asset_categories_name', table_name='asset_categories')
    op.drop_table('asset_categories')
