"""add bill of materials tables

Revision ID: 0b9ae80e3222
Revises: prodinv_0001
Create Date: 2026-07-19 08:42:24.661284

R-07 Wave 0: the shared BillOfMaterial/BillOfMaterialLine spine. Two brand-new
tables -- no changes to any existing table.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0b9ae80e3222'
down_revision = 'prodinv_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('bills_of_material',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('manufacturing_mode', sa.String(length=20), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('product_id', name='uq_bills_of_material_product_id'),
    )
    op.create_table('bill_of_material_lines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bom_id', sa.Integer(), sa.ForeignKey('bills_of_material.id'), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('component_product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('quantity_per', sa.Numeric(precision=15, scale=4), nullable=False),
        sa.Column('uom_id', sa.Integer(), sa.ForeignKey('units_of_measure.id'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('bill_of_material_lines', schema=None) as b:
        b.create_index('ix_bill_of_material_lines_bom_id', ['bom_id'])


def downgrade():
    with op.batch_alter_table('bill_of_material_lines', schema=None) as b:
        b.drop_index('ix_bill_of_material_lines_bom_id')
    op.drop_table('bill_of_material_lines')
    op.drop_table('bills_of_material')
