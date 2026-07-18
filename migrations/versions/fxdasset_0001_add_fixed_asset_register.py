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

    # fixed_assets table added by Task 3 -- placeholder marker so this task's
    # migration file compiles and applies cleanly on its own.


def downgrade():
    op.drop_index('ix_asset_categories_name', table_name='asset_categories')
    op.drop_table('asset_categories')
