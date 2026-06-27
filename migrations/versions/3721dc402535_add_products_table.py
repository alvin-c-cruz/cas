"""add products table

Revision ID: 3721dc402535
Revises: d8ff3e02d0c0
Create Date: 2026-06-27 19:21:11.084411

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3721dc402535'
down_revision = 'd8ff3e02d0c0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('products',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('default_unit_of_measure_id', sa.Integer(), nullable=True),
    sa.Column('default_unit_price', sa.Numeric(precision=15, scale=2), nullable=True),
    sa.Column('default_account_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['default_account_id'], ['accounts.id'], ),
    sa.ForeignKeyConstraint(['default_unit_of_measure_id'], ['units_of_measure.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_products_code'), ['code'], unique=True)


def downgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_products_code'))

    op.drop_table('products')
