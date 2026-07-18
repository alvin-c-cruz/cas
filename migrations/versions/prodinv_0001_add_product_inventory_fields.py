"""add inventory fields to products (R-03 slice 1)

Adds track_inventory/costing_method/standard_cost/reorder_level -- additive,
nullable-except-track_inventory columns. See
docs/superpowers/specs/2026-07-19-inventory-item-fields-design.md.

Revision ID: prodinv_0001
Revises: 600ef1b526b4
Create Date: 2026-07-19

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'prodinv_0001'
down_revision = '600ef1b526b4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.add_column(sa.Column('track_inventory', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
        batch_op.add_column(sa.Column('costing_method', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('standard_cost', sa.Numeric(precision=15, scale=2), nullable=True))
        batch_op.add_column(sa.Column('reorder_level', sa.Numeric(precision=15, scale=2), nullable=True))
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.alter_column('track_inventory', server_default=None)


def downgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_column('reorder_level')
        batch_op.drop_column('standard_cost')
        batch_op.drop_column('costing_method')
        batch_op.drop_column('track_inventory')
