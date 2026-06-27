"""add qty/unit_price/uom_text/uom_id/product_id to line items

Revision ID: 82f53dde7e81
Revises: 3721dc402535
Create Date: 2026-06-27 20:01:41.524890

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '82f53dde7e81'
down_revision = '3721dc402535'
branch_labels = None
depends_on = None


def upgrade():
    # Add 5 nullable columns + 2 FKs to all four line item tables.
    with op.batch_alter_table('accounts_payable_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('quantity', sa.Numeric(precision=15, scale=4), nullable=True))
        batch_op.add_column(sa.Column('unit_price', sa.Numeric(precision=15, scale=2), nullable=True))
        batch_op.add_column(sa.Column('uom_text', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('unit_of_measure_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('product_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_ap_items_product_id', 'products', ['product_id'], ['id'])
        batch_op.create_foreign_key('fk_ap_items_uom_id', 'units_of_measure', ['unit_of_measure_id'], ['id'])

    with op.batch_alter_table('cdv_expense_lines', schema=None) as batch_op:
        batch_op.add_column(sa.Column('quantity', sa.Numeric(precision=15, scale=4), nullable=True))
        batch_op.add_column(sa.Column('unit_price', sa.Numeric(precision=15, scale=2), nullable=True))
        batch_op.add_column(sa.Column('uom_text', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('unit_of_measure_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('product_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_cdv_lines_uom_id', 'units_of_measure', ['unit_of_measure_id'], ['id'])
        batch_op.create_foreign_key('fk_cdv_lines_product_id', 'products', ['product_id'], ['id'])

    with op.batch_alter_table('crv_revenue_lines', schema=None) as batch_op:
        batch_op.add_column(sa.Column('quantity', sa.Numeric(precision=15, scale=4), nullable=True))
        batch_op.add_column(sa.Column('unit_price', sa.Numeric(precision=15, scale=2), nullable=True))
        batch_op.add_column(sa.Column('uom_text', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('unit_of_measure_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('product_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_crv_lines_uom_id', 'units_of_measure', ['unit_of_measure_id'], ['id'])
        batch_op.create_foreign_key('fk_crv_lines_product_id', 'products', ['product_id'], ['id'])

    with op.batch_alter_table('sales_invoice_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('quantity', sa.Numeric(precision=15, scale=4), nullable=True))
        batch_op.add_column(sa.Column('unit_price', sa.Numeric(precision=15, scale=2), nullable=True))
        batch_op.add_column(sa.Column('uom_text', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('unit_of_measure_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('product_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_si_items_product_id', 'products', ['product_id'], ['id'])
        batch_op.create_foreign_key('fk_si_items_uom_id', 'units_of_measure', ['unit_of_measure_id'], ['id'])


def downgrade():
    with op.batch_alter_table('sales_invoice_items', schema=None) as batch_op:
        batch_op.drop_constraint('fk_si_items_uom_id', type_='foreignkey')
        batch_op.drop_constraint('fk_si_items_product_id', type_='foreignkey')
        batch_op.drop_column('product_id')
        batch_op.drop_column('unit_of_measure_id')
        batch_op.drop_column('uom_text')
        batch_op.drop_column('unit_price')
        batch_op.drop_column('quantity')

    with op.batch_alter_table('crv_revenue_lines', schema=None) as batch_op:
        batch_op.drop_constraint('fk_crv_lines_product_id', type_='foreignkey')
        batch_op.drop_constraint('fk_crv_lines_uom_id', type_='foreignkey')
        batch_op.drop_column('product_id')
        batch_op.drop_column('unit_of_measure_id')
        batch_op.drop_column('uom_text')
        batch_op.drop_column('unit_price')
        batch_op.drop_column('quantity')

    with op.batch_alter_table('cdv_expense_lines', schema=None) as batch_op:
        batch_op.drop_constraint('fk_cdv_lines_product_id', type_='foreignkey')
        batch_op.drop_constraint('fk_cdv_lines_uom_id', type_='foreignkey')
        batch_op.drop_column('product_id')
        batch_op.drop_column('unit_of_measure_id')
        batch_op.drop_column('uom_text')
        batch_op.drop_column('unit_price')
        batch_op.drop_column('quantity')

    with op.batch_alter_table('accounts_payable_items', schema=None) as batch_op:
        batch_op.drop_constraint('fk_ap_items_uom_id', type_='foreignkey')
        batch_op.drop_constraint('fk_ap_items_product_id', type_='foreignkey')
        batch_op.drop_column('product_id')
        batch_op.drop_column('unit_of_measure_id')
        batch_op.drop_column('uom_text')
        batch_op.drop_column('unit_price')
        batch_op.drop_column('quantity')
