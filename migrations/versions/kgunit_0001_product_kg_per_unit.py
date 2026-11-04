"""Product KG per unit

Owner, 4 Nov 2026 (Philgen bug reports of 30 Oct on SO 0004): the SO and the Job Order
Slip show a second unit, KG, beside the selling unit (PACKS). One nullable number on the
product master -- the weight of one unit in KG (a 100 g pack is 0.1). Existing products
stay blank and show no KG figures until it is filled in.

Revision ID: kgunit_0001
Revises: custbs_0001
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = 'kgunit_0001'
down_revision = 'custbs_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kg_per_unit', sa.Numeric(precision=15, scale=6), nullable=True))


def downgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_column('kg_per_unit')
