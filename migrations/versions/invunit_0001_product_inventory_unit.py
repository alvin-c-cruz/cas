"""Product inventory unit (generalises KG per unit)

Owner, 5 Nov 2026, on the live print of Philgen SO 0005: "the BY WEIGHT column should also
have Qty Unit and Price. because there are items that uses different UOM, ei. Cans", then
"change BY WEIGHT to Company Inventory". The second unit on the SO and the Job Order Slip is no
longer fixed to KG: the product names its INVENTORY UNIT (any unit of measure) and how many of
it make one selling unit.

- products.kg_per_unit is renamed products.inventory_qty_per_unit (same Numeric(15,6)).
- products.inventory_unit_id is added (FK units_of_measure, nullable).
- A product that already had a KG figure gets unit KG. If such a product exists and no KG unit
  does, one is created, so no figure is left without its unit. (On Philgen, 5 Nov 2026, no
  product had a KG figure yet.)

Downgrade keeps only the KG figures (the others have no meaning as KG) and drops the unit.

Revision ID: invunit_0001
Revises: kgunit_0001
Create Date: 2026-11-05
"""
import sqlalchemy as sa
from alembic import op

revision = 'invunit_0001'
down_revision = 'kgunit_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.alter_column('kg_per_unit', new_column_name='inventory_qty_per_unit',
                              existing_type=sa.Numeric(precision=15, scale=6),
                              existing_nullable=True)
        batch_op.add_column(sa.Column('inventory_unit_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_products_inventory_unit', 'units_of_measure',
                                    ['inventory_unit_id'], ['id'])

    conn = op.get_bind()
    with_factor = conn.execute(sa.text(
        'SELECT COUNT(*) FROM products WHERE inventory_qty_per_unit IS NOT NULL')).scalar()
    if not with_factor:
        return
    kg_id = conn.execute(sa.text(
        "SELECT id FROM units_of_measure WHERE UPPER(TRIM(code)) = 'KG' ORDER BY id LIMIT 1")).scalar()
    if kg_id is None:
        conn.execute(sa.text(
            "INSERT INTO units_of_measure (code, name, is_active, created_at) "
            "VALUES ('KG', 'Kilogram', 1, CURRENT_TIMESTAMP)"))
        kg_id = conn.execute(sa.text(
            "SELECT id FROM units_of_measure WHERE code = 'KG' ORDER BY id LIMIT 1")).scalar()
    conn.execute(sa.text(
        'UPDATE products SET inventory_unit_id = :kg WHERE inventory_qty_per_unit IS NOT NULL'),
        {'kg': kg_id})


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE products SET inventory_qty_per_unit = NULL WHERE inventory_qty_per_unit IS NOT NULL "
        "AND (inventory_unit_id IS NULL OR inventory_unit_id NOT IN "
        "(SELECT id FROM units_of_measure WHERE UPPER(TRIM(code)) = 'KG'))"))
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_constraint('fk_products_inventory_unit', type_='foreignkey')
        batch_op.drop_column('inventory_unit_id')
        batch_op.alter_column('inventory_qty_per_unit', new_column_name='kg_per_unit',
                              existing_type=sa.Numeric(precision=15, scale=6),
                              existing_nullable=True)
