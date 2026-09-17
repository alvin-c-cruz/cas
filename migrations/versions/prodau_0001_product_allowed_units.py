"""Per-product allowed units for no-PO receiving lines.

Purely ADDITIVE — one new association table, no existing table altered.
create_table needs no batch wrapper; all constraints are NAMED so a later batch
rebuild can reproduce them.

Revision ID: prodau_0001
Revises: apamd_0001
"""
import sqlalchemy as sa
from alembic import op

revision = 'prodau_0001'
down_revision = 'apamd_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'product_allowed_units',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('unit_of_measure_id', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_product_allowed_units'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'],
                                name='fk_product_allowed_units_product'),
        sa.ForeignKeyConstraint(['unit_of_measure_id'], ['units_of_measure.id'],
                                name='fk_product_allowed_units_unit'),
        sa.UniqueConstraint('product_id', 'unit_of_measure_id',
                            name='uq_product_allowed_units_product_unit'),
    )
    op.create_index('ix_product_allowed_units_product_id',
                    'product_allowed_units', ['product_id'])


def downgrade():
    op.drop_index('ix_product_allowed_units_product_id',
                  table_name='product_allowed_units')
    op.drop_table('product_allowed_units')
