"""add product_categories master table

Revision ID: prodcat_0001
Revises: ca5f99361716
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa

revision = 'prodcat_0001'
down_revision = 'ca5f99361716'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'product_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'],
                                name='fk_product_categories_created_by'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_product_categories_code', 'product_categories', ['code'], unique=True)


def downgrade():
    op.drop_index('ix_product_categories_code', table_name='product_categories')
    op.drop_table('product_categories')
